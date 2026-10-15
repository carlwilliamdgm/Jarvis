"""Tests de validation de l'authentification des appareils de confiance (Localhost & Tailscale)."""

import os
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from interface_morphique import server
from interface_morphique.server import est_adresse_de_confiance


class TestTrustedDevicesAuth(unittest.TestCase):
    def setUp(self):
        self.original_key = os.environ.get("JARVIS_API_KEY")
        self.original_key_hash = os.environ.get("JARVIS_API_KEY_HASH")
        os.environ["JARVIS_API_KEY"] = "super_secret_test_token_12345"
        os.environ.pop("JARVIS_API_KEY_HASH", None)
        self.profile = {"security": {"remote_totp": {"secret": "JBSWY3DPEHPK3PXP", "last_accepted_step": -1}}}
        server._REMOTE_AUTH_SESSIONS.clear()
        server._REMOTE_TOTP_FAILURES.clear()

        @contextmanager
        def profile_transaction():
            yield self.profile

        self.profile_transaction_patch = patch("context_engine.user_profile.transaction_profil", profile_transaction)
        self.profile_transaction_patch.start()
        self.bearer_verification_patch = patch.object(server, "_remote_bearer_matches", return_value=True)
        self.bearer_verification_patch.start()

    @staticmethod
    def request_from(host, scheme="https", authorization=None):
        headers = []
        if authorization:
            headers.append((b"authorization", authorization.encode("ascii")))
        return Request({
            "type": "http", "http_version": "1.1", "method": "GET", "scheme": scheme,
            "path": "/", "raw_path": b"/", "query_string": b"", "headers": headers,
            "client": (host, 5000), "server": ("testserver", 443 if scheme == "https" else 80),
        })

    def tearDown(self):
        self.profile_transaction_patch.stop()
        self.bearer_verification_patch.stop()
        server._REMOTE_AUTH_SESSIONS.clear()
        server._REMOTE_TOTP_FAILURES.clear()
        if self.original_key is not None:
            os.environ["JARVIS_API_KEY"] = self.original_key
        else:
            os.environ.pop("JARVIS_API_KEY", None)
        if self.original_key_hash is not None:
            os.environ["JARVIS_API_KEY_HASH"] = self.original_key_hash
        else:
            os.environ.pop("JARVIS_API_KEY_HASH", None)

    def test_est_adresse_de_confiance_detection(self):
        # Localhost
        self.assertTrue(est_adresse_de_confiance("127.0.0.1"))
        self.assertTrue(est_adresse_de_confiance("::1"))
        self.assertTrue(est_adresse_de_confiance("localhost"))
        self.assertTrue(est_adresse_de_confiance("testclient"))

        # Tailscale IPv4 (100.64.0.0/10)
        self.assertTrue(est_adresse_de_confiance("100.64.0.1"))
        self.assertTrue(est_adresse_de_confiance("100.100.42.15"))
        self.assertTrue(est_adresse_de_confiance("100.127.255.254"))

        # Tailscale IPv6
        self.assertTrue(est_adresse_de_confiance("fd7a:115c:a1e0::1"))

        # IPs non autorisées (Internet public ou LAN classique)
        self.assertFalse(est_adresse_de_confiance("192.168.1.50"))
        self.assertFalse(est_adresse_de_confiance("8.8.8.8"))
        self.assertFalse(est_adresse_de_confiance("203.0.113.19"))
        self.assertFalse(est_adresse_de_confiance(None))

    def test_localhost_access_without_bearer_token(self):
        """Sur localhost (ou testclient), l'accès direct est autorisé sans clé."""
        self.assertTrue(server.verify_api_key(self.request_from("127.0.0.1")))

    def test_tailscale_ip_access_without_bearer_token(self):
        """Une requête provenant du Tailnet Tailscale est reconnue comme appareil de confiance."""
        self.assertTrue(server.verify_api_key(self.request_from("100.90.80.70")))

    def test_untrusted_ip_blocked_without_token(self):
        """Une IP externe non approuvée sans jeton d'authentification est bloquée (401)."""
        with self.assertRaises(HTTPException) as raised:
            server.verify_api_key(self.request_from("198.51.100.42"), None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_untrusted_ip_bearer_alone_is_not_enough(self):
        """La clé Bearer principale seule ne donne plus accès à l'API distante."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_token_12345")
        with self.assertRaises(HTTPException) as raised:
            server.verify_api_key(self.request_from("198.51.100.42"), credentials)
        self.assertEqual(raised.exception.status_code, 401)

    def test_remote_session_token_is_rejected_over_http_and_accepted_over_https(self):
        """Un jeton distant éphémère ne doit jamais circuler sur HTTP."""
        token = "remote_session_test_token"
        token_digest = server.hashlib.sha256(token.encode("utf-8")).hexdigest()
        server._REMOTE_AUTH_SESSIONS[token_digest] = time.monotonic() + server._REMOTE_SESSION_TTL_SECONDS
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with self.assertRaises(HTTPException) as raised:
            server.verify_api_key(self.request_from("198.51.100.42", scheme="http"), credentials)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertTrue(server.verify_api_key(self.request_from("198.51.100.42", scheme="https"), credentials))

    def test_argon2id_only_configuration_accepts_existing_remote_sessions(self):
        token = "argon2_configured_remote_session"
        token_digest = server.hashlib.sha256(token.encode("utf-8")).hexdigest()
        server._REMOTE_AUTH_SESSIONS[token_digest] = time.monotonic() + server._REMOTE_SESSION_TTL_SECONDS
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch.dict(os.environ, {"JARVIS_API_KEY": "", "JARVIS_API_KEY_HASH": "$argon2id$test-verifier"}):
            self.assertTrue(server.verify_api_key(self.request_from("198.51.100.42"), credentials))

    def test_untrusted_ip_requires_https_for_session_exchange(self):
        """Le premier facteur et le TOTP ne sont jamais échangés en clair."""
        request = self.request_from("198.51.100.42", scheme="http")
        step = int(time.time() // 30)
        code = server.TotpCodeRequest(code=server._totp_code("JBSWY3DPEHPK3PXP", step))
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_token_12345")
        with self.assertRaises(HTTPException) as raised:
            server.create_remote_session(request, code, Response(), credentials)
        self.assertEqual(raised.exception.status_code, 400)

    def test_untrusted_ip_exchanges_bearer_and_totp_for_ephemeral_session(self):
        """Une session HTTPS issue de Bearer + TOTP fonctionne et un code ne peut pas être rejoué."""
        request = self.request_from("198.51.100.42")
        code = server._totp_code("JBSWY3DPEHPK3PXP", int(time.time() // 30))
        code_request = server.TotpCodeRequest(code=code)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_token_12345")

        response = Response()
        login = server.create_remote_session(request, code_request, response, credentials)
        self.assertEqual(login["expires_in"], 30 * 60)
        self.assertEqual(response.headers.get("cache-control"), "no-store")

        session_token = login["access_token"]
        session_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=session_token)
        self.assertTrue(server.verify_api_key(self.request_from("198.51.100.42"), session_credentials))

        with self.assertRaises(HTTPException) as raised:
            server.create_remote_session(request, code_request, Response(), credentials)
        self.assertEqual(raised.exception.status_code, 401)

    def test_full_remote_session_capacity_rejects_without_consuming_totp(self):
        now = time.monotonic()
        server._REMOTE_AUTH_SESSIONS.update({f"digest-{index}": now + 120 for index in range(server._REMOTE_SESSION_CAPACITY)})
        request = self.request_from("198.51.100.45")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_token_12345")
        code_request = server.TotpCodeRequest(code=server._totp_code("JBSWY3DPEHPK3PXP", int(time.time() // 30)))

        with patch.object(server, "_matching_totp_step") as matching_totp:
            with self.assertRaises(HTTPException) as raised:
                server.create_remote_session(request, code_request, Response(), credentials)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "120")
        self.assertEqual(len(server._REMOTE_AUTH_SESSIONS), server._REMOTE_SESSION_CAPACITY)
        matching_totp.assert_not_called()

    def test_untrusted_ip_is_temporarily_limited_after_five_invalid_totp_codes(self):
        """Cinq échecs après Bearer déclenchent un délai temporaire explicite."""
        request = self.request_from("198.51.100.43")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_token_12345")
        code_request = server.TotpCodeRequest(code="000000")
        with patch.object(server, "_matching_totp_step", return_value=None):
            for attempt in range(server._REMOTE_TOTP_FAILURE_LIMIT):
                with self.assertRaises(HTTPException) as raised:
                    server.create_remote_session(request, code_request, Response(), credentials)
                expected_status = 429 if attempt + 1 == server._REMOTE_TOTP_FAILURE_LIMIT else 401
                self.assertEqual(raised.exception.status_code, expected_status)

            with self.assertRaises(HTTPException) as raised:
                server.create_remote_session(request, code_request, Response(), credentials)
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.headers["Retry-After"], str(server._REMOTE_TOTP_COOLDOWN_SECONDS))

    def test_untrusted_ip_is_limited_before_argon_after_invalid_bearer_attempts(self):
        request = self.request_from("198.51.100.44")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
        code_request = server.TotpCodeRequest(code="000000")
        with patch.object(server, "_remote_bearer_matches", return_value=False):
            for attempt in range(server._REMOTE_TOTP_FAILURE_LIMIT):
                with self.assertRaises(HTTPException) as raised:
                    server.create_remote_session(request, code_request, Response(), credentials)
                expected_status = 429 if attempt + 1 == server._REMOTE_TOTP_FAILURE_LIMIT else 401
                self.assertEqual(raised.exception.status_code, expected_status)

            with self.assertRaises(HTTPException) as raised:
                server.create_remote_session(request, code_request, Response(), credentials)
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.headers["Retry-After"], str(server._REMOTE_TOTP_COOLDOWN_SECONDS))


if __name__ == "__main__":
    unittest.main()
