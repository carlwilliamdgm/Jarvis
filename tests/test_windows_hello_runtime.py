"""Tests for the Windows Hello credential registry and server flow wiring."""

import base64
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from datashield import windows_hello
from datashield.crypto import crypto_engine
from interface_morphique import server


def make_request(host="testclient", scheme="http", origin="http://localhost:8000"):
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": scheme,
        "path": "/", "raw_path": b"/", "query_string": b"",
        "headers": [(b"origin", origin.encode("ascii"))],
        "client": (host, 5000), "server": ("127.0.0.1", 8000),
        "app": server.app,
    })


class WindowsHelloRegistryTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name) / "hello.dpapi"
        self.protected = {}
        self.protect_patch = patch.object(windows_hello, "protect_secret", side_effect=self._protect)
        self.unprotect_patch = patch.object(windows_hello, "unprotect_secret", side_effect=self._unprotect)
        self.path_patch = patch.object(windows_hello, "_credentials_path", return_value=self.store)
        self.protect_patch.start(); self.unprotect_patch.start(); self.path_patch.start()
        self.addCleanup(self.protect_patch.stop); self.addCleanup(self.unprotect_patch.stop); self.addCleanup(self.path_patch.stop)

    def _protect(self, value, path):
        self.protected[str(path)] = value
        Path(path).write_text("wrapped", encoding="ascii")
        return Path(path)

    def _unprotect(self, path):
        return self.protected[str(path)]

    def test_origin_validation_requires_exact_secure_origin(self):
        self.assertEqual(windows_hello.origin_and_rp_id("http://127.0.0.1:8000"), ("http://127.0.0.1:8000", "127.0.0.1"))
        with self.assertRaises(ValueError):
            windows_hello.origin_and_rp_id("http://greatos.example")
        with self.assertRaises(ValueError):
            windows_hello.origin_and_rp_id("https://greatos.example/path")

    def test_registry_round_trip_and_counter_update(self):
        registration_result = SimpleNamespace(credential_id=b"credential", public_key=b"public", sign_count=1)
        auth_result = SimpleNamespace(new_sign_count=2)
        fake_ceremonies = SimpleNamespace(
            create_registration_options=lambda **kw: {"ceremony_id": "reg-id", "publicKey": {}},
            verify_registration=lambda **kw: registration_result,
            create_authentication_options=lambda **kw: {"ceremony_id": "auth-id", "publicKey": {"allow": kw["credential_ids"][0]}},
            verify_authentication=lambda **kw: auth_result,
        )
        with patch.object(windows_hello, "_CEREMONIES", fake_ceremonies):
            with self.assertRaises(ValueError):
                windows_hello.begin_registration("http://127.0.0.1:8000")
        with patch.object(windows_hello, "_CEREMONIES", fake_ceremonies):
            options = windows_hello.begin_registration("http://localhost:8000")
            windows_hello.finish_registration("http://localhost:8000", options["ceremony_id"], {
                "response": {}, "clientExtensionResults": {"prf": {"enabled": True}},
            })
            self.assertTrue(windows_hello.has_credential("http://localhost:8000"))
            self.assertTrue(windows_hello.has_prf_credential("http://localhost:8000"))
            auth_options = windows_hello.begin_authentication("http://localhost:8000")
            self.assertEqual(auth_options["publicKey"]["allow"], b"credential")
            self.assertTrue(windows_hello.finish_authentication("http://localhost:8000", auth_options["ceremony_id"], {"response": {}}))
            prf_options = windows_hello.begin_key_unlock("http://localhost:8000")
            self.assertEqual(len(windows_hello.finish_prf_authentication(
                "http://localhost:8000", prf_options["ceremony_id"], {"response": {}}
            )), 32)
        persisted = json.loads(self.protected[str(self.store)])
        self.assertEqual(persisted["http://localhost:8000"]["sign_count"], 2)
        self.assertEqual(base64.b64decode(persisted["http://localhost:8000"]["public_key"]), b"public")
        self.assertEqual(len(base64.b64decode(persisted["http://localhost:8000"]["prf_salt"])), 32)

    def test_registration_refuses_to_replace_an_existing_credential(self):
        registration_result = SimpleNamespace(credential_id=b"first", public_key=b"public", sign_count=1)
        fake_ceremonies = SimpleNamespace(
            create_registration_options=lambda **kw: {"ceremony_id": "reg-id", "publicKey": {}},
            verify_registration=lambda **kw: registration_result,
        )
        with patch.object(windows_hello, "_CEREMONIES", fake_ceremonies):
            options = windows_hello.begin_registration("http://localhost:8000")
            windows_hello.finish_registration("http://localhost:8000", options["ceremony_id"], {
                "response": {}, "clientExtensionResults": {"prf": {"enabled": True}},
            })
            original = self.protected[str(self.store)]
            with self.assertRaisesRegex(ValueError, "existe déjà"):
                windows_hello.begin_registration("http://localhost:8000")
            self.assertEqual(self.protected[str(self.store)], original)

    def test_remote_factor_credential_does_not_require_prf(self):
        registration_result = SimpleNamespace(credential_id=b"remote", public_key=b"public", sign_count=1)
        fake_ceremonies = SimpleNamespace(
            create_registration_options=lambda **kw: {"ceremony_id": "remote-reg", "publicKey": {"extensions": {"prf": {}}} if kw["enable_prf"] else {}},
            verify_registration=lambda **kw: registration_result,
        )
        origin = "https://greatos.example.test"
        with patch.object(windows_hello, "_CEREMONIES", fake_ceremonies):
            options = windows_hello.begin_registration(origin, require_prf=False)
            self.assertNotIn("extensions", options["publicKey"])
            windows_hello.finish_registration(origin, options["ceremony_id"], {"response": {}}, require_prf=False)
        self.assertTrue(windows_hello.has_credential(origin))
        self.assertFalse(windows_hello.has_prf_credential(origin))

    def test_local_data_shield_credential_still_requires_prf(self):
        registration_result = SimpleNamespace(credential_id=b"local", public_key=b"public", sign_count=1)
        fake_ceremonies = SimpleNamespace(
            create_registration_options=lambda **kw: {"ceremony_id": "local-reg", "publicKey": {}},
            verify_registration=lambda **kw: registration_result,
        )
        with patch.object(windows_hello, "_CEREMONIES", fake_ceremonies):
            options = windows_hello.begin_registration("http://localhost:8000")
            with self.assertRaisesRegex(ValueError, "ne prend pas en charge PRF"):
                windows_hello.finish_registration("http://localhost:8000", options["ceremony_id"], {"response": {}})


class WindowsHelloRouteTests(unittest.TestCase):
    def tearDown(self):
        server._REMOTE_AUTH_SESSIONS.clear()
        server._REMOTE_TOTP_FAILURES.clear()

    def test_local_hello_unlock_requires_successful_assertion_before_prf_unwrap(self):
        body = server.WebAuthnPrfResponseRequest(ceremony_id="a" * 24, credential={"response": {}}, prf_output="A" * 43)
        request = make_request()
        with patch("datashield.windows_hello.finish_authentication", return_value=True) as assertion, \
             patch.object(crypto_engine, "unlock_with_hello_prf") as unlock, \
             patch.object(server, "_start_runtime_services"), \
             patch.object(type(crypto_engine), "is_enabled", new_callable=unittest.mock.PropertyMock, return_value=True):
            result = server.finish_hello_unlock(request, body)
        assertion.assert_called_once()
        unlock.assert_called_once()
        self.assertTrue(result["unlocked"])

    def test_failed_hello_assertion_never_releases_datashield_key(self):
        body = server.WebAuthnPrfResponseRequest(ceremony_id="c" * 24, credential={"response": {}}, prf_output="A" * 43)
        with patch("datashield.windows_hello.finish_authentication", side_effect=ValueError("bad assertion")), \
             patch.object(crypto_engine, "unlock_with_hello_prf") as unlock:
            with self.assertRaises(server.HTTPException) as error:
                server.finish_hello_unlock(make_request(), body)
        self.assertEqual(error.exception.status_code, 401)
        unlock.assert_not_called()

    def test_prf_key_confirmation_is_disabled_by_windows_session_policy(self):
        body = server.WebAuthnPrfResponseRequest(
            ceremony_id="d" * 24, credential={"response": {}}, prf_output="A" * 43,
        )
        with patch.object(server, "_require_datashield_unlocked"), \
             patch("datashield.windows_hello.finish_prf_authentication") as finish:
            with self.assertRaises(server.HTTPException) as error:
                server.confirm_hello_key_enrollment(make_request(), body)
        self.assertEqual(error.exception.status_code, 409)
        finish.assert_not_called()

    def test_prf_enrollment_rejects_development_origin(self):
        with self.assertRaises(server.HTTPException) as raised:
            server._require_local_hello_origin(make_request(origin="http://localhost:5173"))
        self.assertEqual(raised.exception.status_code, 403)

    def test_dpapi_recovery_rejects_tailnet_even_when_device_is_trusted(self):
        request = make_request(host="100.90.80.70")
        with patch.object(server, "_require_datashield_unlocked"):
            with self.assertRaises(server.HTTPException) as raised:
                server.unlock_datashield_with_dpapi(request)
        self.assertEqual(raised.exception.status_code, 403)

    def test_dpapi_recovery_refuses_hello_wrapped_profiles(self):
        request = make_request()
        with patch.object(type(crypto_engine), "is_enabled", new_callable=unittest.mock.PropertyMock, return_value=False), \
             patch.object(type(crypto_engine), "is_hello_wrapped", new_callable=unittest.mock.PropertyMock, return_value=True):
            with self.assertRaises(server.HTTPException) as raised:
                server.unlock_datashield_with_dpapi(request)
        self.assertEqual(raised.exception.status_code, 409)

    def test_remote_hello_uses_same_session_ttl_and_checks_bearer(self):
        request = make_request(host="8.8.8.8", scheme="https")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid")
        with patch.object(server, "_remote_bearer_matches", return_value=True), \
             patch("datashield.windows_hello.finish_authentication", return_value=True):
            response = Response()
            result = server.create_remote_hello_session(
                request,
                server.WebAuthnResponseRequest(ceremony_id="b" * 24, credential={"response": {}}),
                response,
                credentials,
            )
        self.assertEqual(result["expires_in"], 30 * 60)
        self.assertEqual(result["token_type"], "bearer")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(server._remote_session_is_valid(result["access_token"]))

    def test_remote_hello_challenge_requires_valid_bearer_and_disables_caching(self):
        request = make_request(host="8.8.8.8", scheme="https")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid")
        with patch.object(server, "_remote_bearer_matches", return_value=True), \
             patch("datashield.windows_hello.begin_authentication", return_value={"ceremony_id": "id", "publicKey": {}}):
            response = Response()
            result = server.begin_remote_hello_session(request, response, credentials)
        self.assertEqual(result["ceremony_id"], "id")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

        with patch.object(server, "_remote_bearer_matches", return_value=False), \
             patch("datashield.windows_hello.begin_authentication") as begin:
            with self.assertRaises(server.HTTPException) as error:
                server.begin_remote_hello_session(request, Response(), credentials)
        self.assertEqual(error.exception.status_code, 401)
        begin.assert_not_called()

    def test_server_stays_available_without_loading_profile_while_locked(self):
        async def exercise_lifespan():
            with patch.object(type(crypto_engine), "is_enabled", new_callable=unittest.mock.PropertyMock, return_value=False), \
                 patch.object(server, "initialiser") as initialize_profile:
                async with server.lifespan(server.app):
                    self.assertFalse(server.app.state.runtime_services_started)
                initialize_profile.assert_not_called()

        asyncio.run(exercise_lifespan())


if __name__ == "__main__":
    unittest.main()
