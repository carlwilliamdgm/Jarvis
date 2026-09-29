# tests/test_syncsphere_crypto.py
"""Tests unitaires pour le chiffrement AES-256-GCM des snapshots SyncSphere (.gos).

Couvre :
- Création et restauration de snapshots en clair (compatibilité ascendante).
- Création et restauration de snapshots intégralement chiffrés.
- Validation du magic header et détection du format (est_chiffre).
- Protection contre la restauration sans clé (PermissionError explicite).
- Protection contre l'altération ou clé incorrecte (PermissionError).
- Détection du statut chiffré dans lister_snapshots.
- Présence des indicateurs de sécurité dans les outils publics SyncSphere.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from datashield.crypto import BLOB_HEADER, CryptoEngine, crypto_engine
from syncsphere.snapshot import SnapshotManager
from syncsphere.tools import creer_snapshot_systeme_tool, lister_snapshots_systeme_tool

TEST_PASSPHRASE = b"syncsphere-master-key-2026"


@pytest.fixture()
def mock_crypto_engine():
    """Crée un moteur crypto isolé avec une clé configurée."""
    engine = CryptoEngine.__new__(CryptoEngine)
    import threading
    engine._lock = threading.Lock()
    engine._passphrase = TEST_PASSPHRASE
    return engine


@pytest.fixture()
def mock_disabled_crypto():
    """Crée un moteur crypto sans clé."""
    engine = CryptoEngine.__new__(CryptoEngine)
    import threading
    engine._lock = threading.Lock()
    engine._passphrase = None
    return engine


@pytest.fixture()
def temp_environment(tmp_path: Path):
    """Crée un environnement isolé pour tester SyncSphere."""
    root_dir = tmp_path / "greatos_root"
    root_dir.mkdir()
    # Création des fichiers d'état critiques
    (root_dir / "memory.json").write_text(json.dumps({"utilisateur": "Carl", "session": "test"}), encoding="utf-8")
    (root_dir / "goals.json").write_text(json.dumps({"objectifs": ["Sécuriser GreatOS"]}), encoding="utf-8")
    (root_dir / "voice_state.json").write_text(json.dumps({"etat": "IDLE"}), encoding="utf-8")

    mgr = SnapshotManager(root_dir=root_dir)
    return root_dir, mgr


class TestSyncSphereCrypto:
    def test_unencrypted_snapshot_creation_and_restoration(self, temp_environment, mock_disabled_crypto):
        """Un snapshot créé sans chiffrement se restaure parfaitement."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_disabled_crypto):
            archive = mgr.creer_snapshot(nom="snap_clair.gos", chiffrer=False)
            assert archive.exists()
            assert not mgr.est_chiffre(archive)

            # Modifier memory.json pour vérifier la restauration
            (root_dir / "memory.json").write_text(json.dumps({"utilisateur": "Altere"}), encoding="utf-8")

            res = mgr.restaurer_snapshot(archive)
            assert res["succes"] is True
            assert res["chiffre"] is False
            assert "memory.json" in res["fichiers_restaures"]

            restaure = json.loads((root_dir / "memory.json").read_text(encoding="utf-8"))
            assert restaure["utilisateur"] == "Carl"

    def test_encrypted_snapshot_creation_and_restoration(self, temp_environment, mock_crypto_engine):
        """Un snapshot chiffré AES-256-GCM se crée et se restaure avec succès."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            archive = mgr.creer_snapshot(nom="snap_chiffre.gos", chiffrer=True)
            assert archive.exists()
            assert mgr.est_chiffre(archive)

            # Vérifier que le fichier sur disque débute par le magic header
            raw_content = archive.read_bytes()
            assert raw_content[:len(BLOB_HEADER)] == BLOB_HEADER

            # Modifier les fichiers
            (root_dir / "memory.json").write_text(json.dumps({"utilisateur": "Detruit"}), encoding="utf-8")

            res = mgr.restaurer_snapshot(archive)
            assert res["succes"] is True
            assert res["chiffre"] is True

            restaure = json.loads((root_dir / "memory.json").read_text(encoding="utf-8"))
            assert restaure["utilisateur"] == "Carl"

    def test_restore_encrypted_snapshot_without_key_fails(self, temp_environment, mock_crypto_engine, mock_disabled_crypto):
        """Tenter de restaurer un snapshot chiffré sans clé lève une PermissionError."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            archive = mgr.creer_snapshot(nom="snap_verrouille.gos", chiffrer=True)

        with patch("syncsphere.snapshot.crypto_engine", mock_disabled_crypto):
            with pytest.raises(PermissionError, match="JARVIS_CRYPTO_KEY"):
                mgr.restaurer_snapshot(archive)

    def test_restore_encrypted_snapshot_with_wrong_key_fails(self, temp_environment, mock_crypto_engine):
        """Tenter de restaurer avec une mauvaise clé de déchiffrement lève une PermissionError."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            archive = mgr.creer_snapshot(nom="snap_mauvaise_cle.gos", chiffrer=True)

        bad_engine = CryptoEngine.__new__(CryptoEngine)
        import threading
        bad_engine._lock = threading.Lock()
        bad_engine._passphrase = b"mauvaise-cle-incorrecte"

        with patch("syncsphere.snapshot.crypto_engine", bad_engine):
            with pytest.raises(PermissionError, match="clé incorrecte"):
                mgr.restaurer_snapshot(archive)

    def test_lister_snapshots_shows_encryption_status(self, temp_environment, mock_crypto_engine):
        """lister_snapshots rapporte fidèlement l'état chiffré ou non de chaque archive."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            mgr.creer_snapshot(nom="snap_1.gos", chiffrer=True)
            mgr.creer_snapshot(nom="snap_2.gos", chiffrer=False)

            liste = mgr.lister_snapshots()
            assert len(liste) == 2
            map_chiffre = {item["nom"]: item["chiffre"] for item in liste}
            assert map_chiffre["snap_1.gos"] is True
            assert map_chiffre["snap_2.gos"] is False

    def test_syncsphere_tools_display_lock_badges(self, temp_environment, mock_crypto_engine):
        """Les outils publics SyncSphere indiquent [🔒 Chiffré] ou [🔓 Non chiffré]."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.snapshot_manager", mgr), \
             patch("syncsphere.tools.snapshot_manager", mgr), \
             patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):

            msg_creer = creer_snapshot_systeme_tool("test_badge.gos")
            assert "[🔒 Chiffré]" in msg_creer

            msg_liste = lister_snapshots_systeme_tool()
            assert "[🔒 Chiffré]" in msg_liste
