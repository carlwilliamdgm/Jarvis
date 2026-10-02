import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning import capability_proposals


class TestCapabilityProposals(unittest.TestCase):
    def test_missing_capability_is_recorded_as_inert_review_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capability_proposals.jsonl"
            with patch.object(capability_proposals, "PROPOSALS_PATH", path):
                record = capability_proposals.proposer_nouvelle_capacite(
                    "calendar.create", "A calendar action was requested."
                )
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["id"], record["id"])
            self.assertEqual(stored["status"], "review_required")
            self.assertFalse(stored["executable"])
            self.assertTrue(stored["approval_required"])
            self.assertIn("NotImplementedError", stored["prototype"])
