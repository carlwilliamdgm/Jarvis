"""Argon2id Bearer verifier and one-time migration tests."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from argon2 import PasswordHasher
except ImportError:  # pragma: no cover - exercised when project dependencies are installed
    PasswordHasher = None

from datashield.env_loader import generer_secrets_production, preparer_cle_api_argon2
from datashield.passwords import verifier_credential
from interface_morphique import server


@unittest.skipIf(PasswordHasher is None, "argon2-cffi is required")
class TestBearerArgonAuth(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp_dir.cleanup)
        self.env_patch = patch.dict(os.environ, {
            "JARVIS_API_KEY": "", "JARVIS_API_KEY_HASH": "", "GREATOS_ENV": "development",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        server._BEARER_HASH_CACHE_FINGERPRINT = None
        server._BEARER_HASH_CACHE_PHC = None

    def test_legacy_env_key_is_replaced_by_phc_and_revealed_once(self):
        env_path = Path(self.temp_dir.name) / ".env"
        env_path.write_text("OTHER_SETTING=value\nJARVIS_API_KEY=legacy-secret-value\n", encoding="utf-8")

        revealed = preparer_cle_api_argon2(env_path)

        persisted = env_path.read_text(encoding="utf-8")
        self.assertEqual(revealed, "legacy-secret-value")
        self.assertNotIn("JARVIS_API_KEY=", persisted)
        self.assertNotIn("legacy-secret-value", persisted)
        verifier = os.environ["JARVIS_API_KEY_HASH"]
        self.assertTrue(verifier.startswith("$argon2id$"))
        self.assertTrue(verifier_credential(revealed, verifier))
        self.assertFalse(verifier_credential("another-secret", verifier))

        self.assertIsNone(preparer_cle_api_argon2(env_path))

    def test_new_production_secrets_store_only_argon2id_verifier(self):
        env_path = Path(self.temp_dir.name) / ".env"

        generated = generer_secrets_production(env_path)

        persisted = env_path.read_text(encoding="utf-8")
        self.assertNotIn("JARVIS_API_KEY=", persisted)
        self.assertNotIn(generated["JARVIS_API_KEY"], persisted)
        self.assertTrue(persisted.count("JARVIS_API_KEY_HASH=") == 1)
        verifier = persisted.split("JARVIS_API_KEY_HASH=", 1)[1].splitlines()[0]
        self.assertTrue(verifier_credential(generated["JARVIS_API_KEY"], verifier))

    def test_bearer_verification_uses_persisted_hash(self):
        secret = "configured-remote-bearer-secret"
        with patch.dict(os.environ, {
            "JARVIS_API_KEY": "",
            "JARVIS_API_KEY_HASH": PasswordHasher().hash(secret),
        }):
            self.assertTrue(server._remote_bearer_matches(secret))
            self.assertFalse(server._remote_bearer_matches("incorrect-secret"))

    def test_legacy_environment_secret_is_hashed_in_memory_and_rotation_invalidates_cache(self):
        with patch.dict(os.environ, {"JARVIS_API_KEY": "old-secret", "JARVIS_API_KEY_HASH": ""}):
            self.assertTrue(server._remote_bearer_matches("old-secret"))
            self.assertFalse(server._remote_bearer_matches("wrong-secret"))
        with patch.dict(os.environ, {"JARVIS_API_KEY": "new-secret", "JARVIS_API_KEY_HASH": ""}):
            self.assertTrue(server._remote_bearer_matches("new-secret"))
            self.assertFalse(server._remote_bearer_matches("old-secret"))

    def test_plaintext_bearer_is_rejected_in_production(self):
        with patch.dict(os.environ, {
            "GREATOS_ENV": "production",
            "JARVIS_API_KEY": "legacy-secret",
            "JARVIS_API_KEY_HASH": PasswordHasher().hash("legacy-secret"),
        }):
            with self.assertRaisesRegex(RuntimeError, "interdite en production"):
                server._remote_bearer_matches("legacy-secret")


if __name__ == "__main__":
    unittest.main()
