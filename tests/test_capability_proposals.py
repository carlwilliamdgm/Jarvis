import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datashield.crypto import CryptoEngine
from context_engine.encrypted_user_store import ENCRYPTED_JSON_KEY
from learning import capability_proposals


class TestCapabilityProposals(unittest.TestCase):
    def test_missing_capability_is_recorded_as_inert_review_candidate(self):
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            path = Path(temporary) / "capability_proposals.jsonl"
            engine = CryptoEngine.__new__(CryptoEngine)
            engine._passphrase = b"isolated-proposal-test-key"
            engine._lock = threading.Lock()
            with (
                patch.object(capability_proposals, "PROPOSALS_PATH", path),
                patch("context_engine.encrypted_user_store.crypto_engine", engine),
                patch("datashield.crypto.PBKDF2_ITERATIONS", 1),
            ):
                record = capability_proposals.proposer_nouvelle_capacite(
                    "calendar.create", "A calendar action was requested."
                )
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(set(raw), {ENCRYPTED_JSON_KEY})
                self.assertNotIn("calendar.create", path.read_text(encoding="utf-8"))
                stored = json.loads(engine.decrypt(raw[ENCRYPTED_JSON_KEY], strict=True))
            self.assertEqual(stored["id"], record["id"])
            self.assertEqual(stored["status"], "review_required")
            self.assertFalse(stored["executable"])
            self.assertTrue(stored["approval_required"])
            self.assertIn("NotImplementedError", stored["prototype"])
