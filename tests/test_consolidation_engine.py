import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from datashield.crypto import CryptoEngine
from context_engine.encrypted_user_store import ENCRYPTED_JSON_KEY
from learning import consolidation_engine


@contextmanager
def _patched_crypto():
    engine = CryptoEngine.__new__(CryptoEngine)
    engine._passphrase = b"isolated-consolidation-test-key"
    engine._lock = threading.Lock()
    with (
        patch("context_engine.encrypted_user_store.crypto_engine", engine),
        patch("context_engine.user_profile.crypto_engine", engine),
        patch("datashield.crypto.PBKDF2_ITERATIONS", 1),
    ):
        yield


class TestConsolidationEngine(unittest.TestCase):
    def test_consolide_resultats_recents_dans_profil_isole(self):
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary, _patched_crypto():
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
            matrix_file = json.loads((user_root / "trust_matrix.json").read_text(encoding="utf-8"))
            self.assertEqual(set(matrix_file), {ENCRYPTED_JSON_KEY})
            log_lines = (user_root / "consolidation.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 1)
            self.assertNotIn("filesystem_read", log_lines[0])

    def test_consolidation_planifiee_une_fois_par_jour_a_deux_heures(self):
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary, _patched_crypto():
            root = Path(temporary)
            morning = datetime(2026, 10, 1, 1, 59, tzinfo=timezone.utc)
            run_time = datetime(2026, 10, 1, 2, 1, tzinfo=timezone.utc)
            with patch.object(consolidation_engine, "PROFILES_DIR", root), patch(
                "context_engine.user_profile.PROFILES_DIR", root
            ):
                self.assertIsNone(consolidation_engine.consolider_si_due("bob", morning))
                self.assertIsNotNone(consolidation_engine.consolider_si_due("bob", run_time))
                self.assertIsNone(consolidation_engine.consolider_si_due("bob", run_time))
            state_file = json.loads((root / "bob" / "consolidation-state.json").read_text(encoding="utf-8"))
            self.assertEqual(set(state_file), {ENCRYPTED_JSON_KEY})
