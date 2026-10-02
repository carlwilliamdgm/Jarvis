import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from learning import consolidation_engine


class TestConsolidationEngine(unittest.TestCase):
    def test_consolide_resultats_recents_dans_profil_isole(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_root = root / "alice"
            user_root.mkdir()
            now = datetime(2026, 10, 1, 2, tzinfo=timezone.utc)
            matrix = {
                "domaines": {},
                "historique_resultats": [
                    {"date": (now - timedelta(days=1)).isoformat(), "domaine": "filesystem_read", "succes": True},
                    {"date": (now - timedelta(days=2)).isoformat(), "domaine": "filesystem_read", "succes": False},
                    {"date": (now - timedelta(days=9)).isoformat(), "domaine": "filesystem_read", "succes": True},
                ],
            }
            (user_root / "trust_matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
            with (
                patch.object(consolidation_engine, "PROFILES_DIR", root),
                patch("context_engine.user_profile.PROFILES_DIR", root),
            ):
                result = consolidation_engine.consolider_apprentissages("alice", now)

            self.assertEqual(result["domaines_observes"]["filesystem_read"], {
                "succes": 1, "echecs": 1, "score": 0.5,
            })
            self.assertTrue((user_root / "consolidation.log").exists())

    def test_consolidation_planifiee_une_fois_par_jour_a_deux_heures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            morning = datetime(2026, 10, 1, 1, 59, tzinfo=timezone.utc)
            run_time = datetime(2026, 10, 1, 2, 1, tzinfo=timezone.utc)
            with patch.object(consolidation_engine, "PROFILES_DIR", root), patch(
                "context_engine.user_profile.PROFILES_DIR", root
            ):
                self.assertIsNone(consolidation_engine.consolider_si_due("bob", morning))
                self.assertIsNotNone(consolidation_engine.consolider_si_due("bob", run_time))
                self.assertIsNone(consolidation_engine.consolider_si_due("bob", run_time))
