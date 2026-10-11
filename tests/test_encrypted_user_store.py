import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from datashield.crypto import CryptoEngine
from context_engine.encrypted_user_store import (
    ENCRYPTED_JSON_KEY,
    append_encrypted_jsonl,
    load_encrypted_json,
    migrate_encrypted_jsonl,
    save_encrypted_json,
)


class EncryptedUserStoreTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        self._storage = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self._storage.cleanup)
        self.root = Path(self._storage.name)

        self.engine = CryptoEngine.__new__(CryptoEngine)
        self.engine._passphrase = b"isolated-encrypted-store-test-key"
        self.engine._lock = threading.Lock()
        self._crypto_patch = patch("context_engine.encrypted_user_store.crypto_engine", self.engine)
        self._kdf_patch = patch("datashield.crypto.PBKDF2_ITERATIONS", 1)
        self._crypto_patch.start()
        self._kdf_patch.start()
        self.addCleanup(self._crypto_patch.stop)
        self.addCleanup(self._kdf_patch.stop)

    def test_json_round_trip_writes_only_ciphertext(self):
        path = self.root / "trust_matrix.json"
        value = {"domaines": {"web_recherche": {"niveau": 2}}}

        save_encrypted_json(path, value)

        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(raw), {ENCRYPTED_JSON_KEY})
        self.assertNotIn("web_recherche", json.dumps(raw))
        self.assertEqual(load_encrypted_json(path, dict), value)

    def test_legacy_json_is_migrated_atomically_without_data_loss(self):
        path = self.root / "trust_matrix.json"
        value = {"domaines": {"files_read": {"niveau": 1}}}
        path.write_text(json.dumps(value), encoding="utf-8")

        loaded = load_encrypted_json(path, dict)

        self.assertEqual(loaded, value)
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {ENCRYPTED_JSON_KEY})
        self.assertNotIn("files_read", json.dumps(stored))
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_missing_key_fails_closed_and_preserves_legacy_file(self):
        path = self.root / "user_state.json"
        plaintext = '{"private_marker":"test"}'
        path.write_text(plaintext, encoding="utf-8")
        self.engine._passphrase = None

        with self.assertRaisesRegex(RuntimeError, "chiffrement DataShield indisponible"):
            load_encrypted_json(path, dict)
        with self.assertRaisesRegex(RuntimeError, "chiffrement DataShield indisponible"):
            save_encrypted_json(self.root / "new.json", {"x": 1})

        self.assertEqual(path.read_text(encoding="utf-8"), plaintext)
        self.assertFalse((self.root / "new.json").exists())

    def test_tampered_envelope_is_refused_without_replacement(self):
        path = self.root / "trust_matrix.json"
        save_encrypted_json(path, {"domaines": {"x": {"niveau": 3}}})
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope[ENCRYPTED_JSON_KEY] = "tampered"
        path.write_text(json.dumps(envelope), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "illisibles"):
            load_encrypted_json(path, dict)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), envelope)

    def test_jsonl_records_are_encrypted_and_legacy_lines_migrate(self):
        path = self.root / "consolidation.log"
        old_record = {"domaines_observes": {"private_marker": {"score": 1.0}}}
        path.write_text(json.dumps(old_record) + "\n", encoding="utf-8")

        append_encrypted_jsonl(path, {"domaines_observes": {"next": {"score": 0.5}}})

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("private_marker", path.read_text(encoding="utf-8"))
        decoded = [
            self.engine.decrypt(json.loads(line)[ENCRYPTED_JSON_KEY], strict=True)
            for line in lines
        ]
        self.assertEqual(json.loads(decoded[0]), old_record)
        self.assertEqual(json.loads(decoded[1])["domaines_observes"]["next"]["score"], 0.5)

    def test_jsonl_migration_does_not_add_or_drop_records(self):
        path = self.root / "consolidation.log"
        records = [{"entry": 1}, {"entry": 2}]
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

        migrate_encrypted_jsonl(path)

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(records))
        restored = [
            json.loads(self.engine.decrypt(json.loads(line)[ENCRYPTED_JSON_KEY], strict=True))
            for line in lines
        ]
        self.assertEqual(restored, records)

    def test_corrupted_jsonl_is_not_replaced(self):
        path = self.root / "consolidation.log"
        path.write_text("{bad line\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "Journal utilisateur illisible"):
            append_encrypted_jsonl(path, {"new": True})
        self.assertEqual(path.read_text(encoding="utf-8"), "{bad line\n")


if __name__ == "__main__":
    unittest.main()
