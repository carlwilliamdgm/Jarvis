import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from datashield.webauthn_auth import (
    CeremonyCapacityError,
    WebAuthnCeremonies,
    WebAuthnError,
)


class TestWebAuthnCeremonies(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.ceremonies = WebAuthnCeremonies(capacity=2, ttl_seconds=10, clock=lambda: self.now)
        self.origin = "https://desktop.example.test"
        self.rp_id = "example.test"

    def test_registration_options_require_platform_uv_and_exact_origin(self):
        result = self.ceremonies.create_registration_options(
            rp_id=self.rp_id, rp_name="GreatOS", user_id=b"profile-id",
            user_name="profile", origins=[self.origin],
        )
        options = result["publicKey"]
        self.assertEqual(options["rp"]["id"], self.rp_id)
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(options["authenticatorSelection"]["authenticatorAttachment"], "platform")
        self.assertEqual(len(options["challenge"]), 43)
        self.assertEqual(self.ceremonies._pending[result["ceremony_id"]].origins, (self.origin,))

    def test_prf_enrollment_requests_extension_and_auth_salt_is_serialized(self):
        registration = self.ceremonies.create_registration_options(
            rp_id=self.rp_id, rp_name="GreatOS", user_id=b"profile-id",
            user_name="profile", origins=[self.origin], enable_prf=True,
        )
        self.assertEqual(registration["publicKey"]["extensions"], {"prf": {}})
        salt = bytes(range(32))
        authentication = self.ceremonies.create_authentication_options(
            rp_id=self.rp_id, origins=[self.origin], credential_ids=[b"known-id"], prf_salt=salt,
        )
        expected = base64.urlsafe_b64encode(salt).rstrip(b"=").decode("ascii")
        self.assertEqual(
            authentication["publicKey"]["extensions"]["prf"]["eval"]["first"], expected
        )
        with self.assertRaises(WebAuthnError):
            self.ceremonies.create_authentication_options(
                rp_id=self.rp_id, origins=[self.origin], credential_ids=[b"known-id"], prf_salt=b"short",
            )

    def test_successful_registration_verifies_challenge_origin_rp_and_uv(self):
        result = self.ceremonies.create_registration_options(
            rp_id=self.rp_id, rp_name="GreatOS", user_id=b"profile-id",
            user_name="profile", origins=[self.origin],
        )
        expected = SimpleNamespace(
            credential_id=b"credential", credential_public_key=b"public-key", sign_count=1,
            aaguid="test-aaguid", user_verified=True,
        )
        with patch("datashield.webauthn_auth.verify_registration_response", return_value=expected) as verify:
            verified = self.ceremonies.verify_registration(
                ceremony_id=result["ceremony_id"], credential={"id": "credential"}
            )
        self.assertEqual(verified.credential_id, b"credential")
        kwargs = verify.call_args.kwargs
        self.assertEqual(kwargs["expected_rp_id"], self.rp_id)
        self.assertEqual(kwargs["expected_origin"], [self.origin])
        self.assertTrue(kwargs["require_user_verification"])
        self.assertEqual(len(kwargs["expected_challenge"]), 32)

    def test_registration_failure_consumes_challenge(self):
        result = self.ceremonies.create_registration_options(
            rp_id=self.rp_id, rp_name="GreatOS", user_id=b"profile-id",
            user_name="profile", origins=[self.origin],
        )
        with patch("datashield.webauthn_auth.verify_registration_response", side_effect=ValueError("invalid")):
            with self.assertRaises(WebAuthnError):
                self.ceremonies.verify_registration(ceremony_id=result["ceremony_id"], credential={})
        with self.assertRaises(WebAuthnError):
            self.ceremonies.verify_registration(ceremony_id=result["ceremony_id"], credential={})

    def test_registration_finish_is_bound_to_the_requested_origin(self):
        result = self.ceremonies.create_registration_options(
            rp_id=self.rp_id, rp_name="GreatOS", user_id=b"profile-id",
            user_name="profile", origins=[self.origin],
        )
        with patch("datashield.webauthn_auth.verify_registration_response") as verify:
            with self.assertRaisesRegex(WebAuthnError, "diffère"):
                self.ceremonies.verify_registration(
                    ceremony_id=result["ceremony_id"], credential={}, origin="http://localhost:8000",
                )
        verify.assert_not_called()

    def test_authentication_options_require_uv_and_allow_only_supplied_credentials(self):
        result = self.ceremonies.create_authentication_options(
            rp_id=self.rp_id, origins=[self.origin], credential_ids=[b"known-id"]
        )
        options = result["publicKey"]
        self.assertEqual(options["userVerification"], "required")
        self.assertEqual(options["allowCredentials"][0]["id"], "a25vd24taWQ")

    def test_successful_assertion_returns_counter_and_checks_credential_id(self):
        result = self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        verified = SimpleNamespace(credential_id=b"credential", new_sign_count=8, user_verified=True)
        with patch("datashield.webauthn_auth.verify_authentication_response", return_value=verified) as verify:
            outcome = self.ceremonies.verify_authentication(
                ceremony_id=result["ceremony_id"], credential_id=b"credential",
                credential={"id": "credential"}, public_key=b"public-key", sign_count=7,
            )
        self.assertEqual(outcome.new_sign_count, 8)
        self.assertTrue(verify.call_args.kwargs["require_user_verification"])

    def test_assertion_rejects_unexpected_credential_id(self):
        result = self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        verified = SimpleNamespace(credential_id=b"other", new_sign_count=1, user_verified=True)
        with patch("datashield.webauthn_auth.verify_authentication_response", return_value=verified):
            with self.assertRaises(WebAuthnError):
                self.ceremonies.verify_authentication(
                    ceremony_id=result["ceremony_id"], credential_id=b"expected",
                    credential={}, public_key=b"public-key", sign_count=0,
                )

    def test_authentication_finish_is_bound_to_the_requested_origin(self):
        result = self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        with patch("datashield.webauthn_auth.verify_authentication_response") as verify:
            with self.assertRaisesRegex(WebAuthnError, "diffère"):
                self.ceremonies.verify_authentication(
                    ceremony_id=result["ceremony_id"], credential_id=b"expected",
                    credential={}, public_key=b"public-key", sign_count=0,
                    origin="http://localhost:8000",
                )
        verify.assert_not_called()

    def test_ceremonies_are_expiring_bounded_and_one_shot(self):
        first = self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        with self.assertRaises(CeremonyCapacityError):
            self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        self.now += 10
        fresh = self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[self.origin])
        with self.assertRaises(WebAuthnError):
            self.ceremonies._consume(first["ceremony_id"], "authentication")
        self.assertEqual(len(self.ceremonies._pending), 1)
        self.assertTrue(fresh["ceremony_id"])

    def test_rejects_non_exact_or_insecure_remote_origin(self):
        for origin in ("https://*.example.test", "http://desktop.example.test", "https://example.test/path"):
            with self.subTest(origin=origin), self.assertRaises(WebAuthnError):
                self.ceremonies.create_authentication_options(rp_id=self.rp_id, origins=[origin])

    def test_rejects_malformed_rp_id(self):
        with self.assertRaises(WebAuthnError):
            self.ceremonies.create_authentication_options(rp_id="example..test", origins=[self.origin])


if __name__ == "__main__":
    unittest.main()
