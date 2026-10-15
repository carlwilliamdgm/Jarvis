"""Tests de l'isolation et de la persistance chiffrée de la gamification."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import context_engine.user_profile as user_profile
from datashield.crypto import CryptoEngine
import progress_tracker.gamification as gamification
from progress_tracker.gamification import (
    ProfilGamification,
    attribuer_xp,
    charger_etat_gamification,
    sauvegarder_etat_gamification,
)


class TestGamificationEncryptedProfile(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=temp_root)
        self.original_profiles_dir = user_profile.PROFILES_DIR
        self.original_legacy_path = gamification._LEGACY_GAMIFICATION_PATH
        user_profile.PROFILES_DIR = Path(self.temp_dir.name)
        gamification._LEGACY_GAMIFICATION_PATH = Path(self.temp_dir.name) / "legacy.json"

        engine = CryptoEngine.__new__(CryptoEngine)
        engine._passphrase = b"isolated-gamification-test-key"
        engine._lock = threading.Lock()
        self.crypto_patch = patch.object(user_profile, "crypto_engine", engine)
        self.kdf_patch = patch("datashield.crypto.PBKDF2_ITERATIONS", 1)
        self.crypto_patch.start()
        self.kdf_patch.start()

    def tearDown(self):
        self.kdf_patch.stop()
        self.crypto_patch.stop()
        user_profile.PROFILES_DIR = self.original_profiles_dir
        gamification._LEGACY_GAMIFICATION_PATH = self.original_legacy_path
        self.temp_dir.cleanup()

    def test_xp_is_persisted_encrypted_and_isolated_per_user(self):
        result = attribuer_xp(125, raison="unit test", user_id="alice")

        self.assertEqual(result["total_xp"], 125)
        self.assertEqual(charger_etat_gamification("alice").points_xp, 125)
        self.assertEqual(charger_etat_gamification("bob").points_xp, 0)

        profile_path = Path(self.temp_dir.name) / "alice" / "profile.json"
        stored = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {"__greatos_encrypted_profile_v1__"})
        self.assertNotIn("125", json.dumps(stored))

    def test_malformed_gamification_state_fails_closed(self):
        profile = user_profile.charger_profil("alice")
        profile["gamification"] = ["invalid"]
        user_profile.sauvegarder_profil(profile, "alice")

        with self.assertRaisesRegex(RuntimeError, "État de gamification invalide"):
            charger_etat_gamification("alice")

    def test_explicit_save_updates_only_selected_profile(self):
        state = ProfilGamification(points_xp=700, niveau=2, titre_rang="Praticien de l'Automatisation", xp_palier_suivant=1500)
        sauvegarder_etat_gamification(state, user_id="alice")

        self.assertEqual(charger_etat_gamification("alice").points_xp, 700)
        self.assertEqual(charger_etat_gamification("bob").points_xp, 0)

    def test_legacy_state_is_migrated_to_active_profile_and_removed_after_verification(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.json"
        legacy_path.write_text(json.dumps({"points_xp": 830, "niveau": 2}), encoding="utf-8")

        with patch("progress_tracker.gamification.resoudre_utilisateur_actif", return_value="alice"):
            migrated = charger_etat_gamification()

        self.assertEqual(migrated.points_xp, 830)
        self.assertFalse(legacy_path.exists())
        self.assertEqual(charger_etat_gamification("alice").points_xp, 830)

    def test_legacy_migration_never_assigns_data_to_another_explicit_user(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.json"
        legacy_path.write_text(json.dumps({"points_xp": 830, "niveau": 2}), encoding="utf-8")

        with patch("progress_tracker.gamification.resoudre_utilisateur_actif", side_effect=lambda user_id=None: user_id or "alice"):
            other_user = charger_etat_gamification("bob")

        self.assertEqual(other_user.points_xp, 0)
        self.assertTrue(legacy_path.exists())

    def test_conflicting_legacy_and_profile_state_is_preserved_and_reported(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.json"
        legacy_path.write_text(json.dumps({"points_xp": 830, "niveau": 2}), encoding="utf-8")
        sauvegarder_etat_gamification(ProfilGamification(points_xp=900, niveau=2), user_id="alice")

        with patch("progress_tracker.gamification.resoudre_utilisateur_actif", return_value="alice"):
            with self.assertRaisesRegex(RuntimeError, "diffèrent"):
                charger_etat_gamification()

        self.assertTrue(legacy_path.exists())

    def test_legacy_file_changed_during_migration_is_restored_and_not_deleted(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.json"
        original_rename = Path.rename
        legacy_path.write_text(json.dumps({"points_xp": 830, "niveau": 2}), encoding="utf-8")

        def concurrent_update(source, target):
            if source == legacy_path:
                legacy_path.write_text(json.dumps({"points_xp": 900, "niveau": 2}), encoding="utf-8")
            return original_rename(source, target)

        with patch("progress_tracker.gamification.resoudre_utilisateur_actif", return_value="alice"):
            with patch.object(Path, "rename", autospec=True, side_effect=concurrent_update):
                with self.assertRaisesRegex(RuntimeError, "source restauré"):
                    charger_etat_gamification()

        self.assertTrue(legacy_path.exists())
        self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["points_xp"], 900)


if __name__ == "__main__":
    unittest.main()
