# tests/test_syncsphere_crypto.py
"""Tests unitaires pour le chiffrement obligatoire AES-256-GCM SyncSphere (.gos).

Couvre :
- Refus fail-closed des snapshots en clair à la création et à la restauration.
- Conservation et identification des archives legacy, sans migration/destruction.
- Création et restauration de snapshots intégralement chiffrés.
- Validation du magic header et détection du format (est_chiffre).
- Protection contre la restauration sans clé (PermissionError explicite).
- Protection contre l'altération ou clé incorrecte (PermissionError).
- Détection du statut chiffré dans lister_snapshots.
- Présence des indicateurs de sécurité dans les outils publics SyncSphere.
"""

from __future__ import annotations

import json
import io
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from datashield.crypto import BLOB_HEADER, CryptoEngine, crypto_engine
from syncsphere import snapshot as snapshot_module
from syncsphere.snapshot import SnapshotManager
from syncsphere.tools import creer_snapshot_systeme_tool, lister_snapshots_systeme_tool

TEST_PASSPHRASE = b"syncsphere-master-key-2026"


@pytest.mark.parametrize(("value", "expected"), [(None, 20), ("1", 1), ("30", 30)])
def test_snapshot_limit_configuration(value, expected):
    assert snapshot_module._configured_snapshot_limit_gib(value) == expected


@pytest.mark.parametrize("value", ["0", "-1", "bad", "1.5"])
def test_snapshot_limit_configuration_rejects_invalid_values(value):
    with pytest.raises(RuntimeError, match="entier positif"):
        snapshot_module._configured_snapshot_limit_gib(value)


def test_snapshot_manager_cleans_dead_process_restore_staging_and_preserves_active_files(tmp_path, monkeypatch):
    root = tmp_path / "profile"
    root.mkdir()
    pid = 987654321
    stale = root / f".memory.json.greatos-restore-{pid}-stage.restore"
    active = root / f".goals.json.greatos-restore-{os.getpid()}-stage.restore"
    unrelated = root / ".voice_state.json.other-tool.restore"
    for candidate in (stale, active, unrelated):
        candidate.write_bytes(b"staged")
    monkeypatch.setattr(snapshot_module.os, "kill", lambda _pid, _sig: (_ for _ in ()).throw(ProcessLookupError()))

    SnapshotManager(root_dir=root)

    assert not stale.exists()
    assert active.exists()
    assert unrelated.exists()


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
    def test_streaming_crypto_is_compatible_with_existing_datashield_blob(self, mock_crypto_engine):
        payload = (b"GreatOS streaming compatibility\x00" * 90000) + b"tail"
        legacy_blob = mock_crypto_engine.encrypt_bytes(payload)
        decrypted = io.BytesIO()
        mock_crypto_engine.decrypt_stream(
            io.BytesIO(legacy_blob), decrypted,
            max_input_bytes=len(legacy_blob), max_output_bytes=len(payload), chunk_size=8191,
        )
        assert decrypted.getvalue() == payload

        encrypted = io.BytesIO()
        with mock_crypto_engine.encrypting_writer(encrypted, max_input_bytes=len(payload)) as writer:
            for offset in range(0, len(payload), 7777):
                writer.write(payload[offset:offset + 7777])
        streaming_blob = encrypted.getvalue()
        assert streaming_blob.startswith(BLOB_HEADER)
        assert mock_crypto_engine.decrypt_bytes(streaming_blob, strict=True) == payload

    def test_streaming_decrypt_rejects_bad_tag_and_discards_partial_output(self, mock_crypto_engine):
        blob = bytearray(mock_crypto_engine.encrypt_bytes(b"authenticated payload" * 10000))
        blob[-1] ^= 0x01
        destination = io.BytesIO()
        with pytest.raises(Exception):
            mock_crypto_engine.decrypt_stream(
                io.BytesIO(blob), destination,
                max_input_bytes=len(blob), max_output_bytes=1024 * 1024,
            )
        assert destination.getvalue() == b""

    def test_restores_pre_streaming_datashield_gos_format(self, temp_environment, mock_crypto_engine):
        root_dir, mgr = temp_environment
        archive_bytes = io.BytesIO()
        payload = b'{"utilisateur":"format-v1"}'
        metadata = json.dumps({
            "version": "1.0", "format": "gos", "timestamp": "20260101_000000",
            "fichiers": ["memory.json"], "chiffre": True, "algorithme": "AES-256-GCM",
        }).encode("utf-8")
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            for name, content in (("memory.json", payload), ("metadata.json", metadata)):
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))

        legacy_encrypted = mgr.snapshots_dir / "legacy-encrypted.gos"
        legacy_encrypted.write_bytes(mock_crypto_engine.encrypt_bytes(archive_bytes.getvalue()))
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            details = mgr.verifier_integrite(legacy_encrypted)
            assert details["fichiers_verifies"] == ["memory.json"]
            result = mgr.restaurer_snapshot(legacy_encrypted)
        assert result["chiffre"] is True
        assert json.loads((root_dir / "memory.json").read_text(encoding="utf-8"))["utilisateur"] == "format-v1"

    def test_plaintext_snapshot_creation_is_rejected(self, temp_environment, mock_disabled_crypto):
        """Aucun appel explicite ne peut contourner le chiffrement obligatoire."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_disabled_crypto):
            with pytest.raises(ValueError, match="en clair sont interdits"):
                mgr.creer_snapshot(nom="snap_clair.gos", chiffrer=False)
            with pytest.raises(RuntimeError, match="DataShield est verrouillé"):
                mgr.creer_snapshot(nom="snap_auto.gos")
        assert not (mgr.snapshots_dir / "snap_clair.gos").exists()
        assert not (mgr.snapshots_dir / "snap_auto.gos").exists()

    def test_encryption_failure_never_publishes_archive(self, temp_environment, mock_crypto_engine):
        _, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            with patch.object(mock_crypto_engine, "encrypting_writer", side_effect=RuntimeError("crypto failure")):
                with pytest.raises(RuntimeError, match="crypto failure"):
                    mgr.creer_snapshot(nom="snap_echec.gos")
        assert not (mgr.snapshots_dir / "snap_echec.gos").exists()
        assert list(mgr.snapshots_dir.glob("*.tmp")) == []

    def test_snapshot_create_verify_restore_never_use_whole_file_bytes_api(self, temp_environment, mock_crypto_engine):
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            with patch("syncsphere.snapshot.Path.read_bytes", side_effect=AssertionError("whole file read")):
                archive = mgr.creer_snapshot(nom="streamed.gos")
                assert mgr.verifier_integrite(archive)["succes"] is True
                (root_dir / "memory.json").write_text('{"utilisateur":"changed"}', encoding="utf-8")
                (root_dir / "voice_state.json").unlink()
                result = mgr.restaurer_snapshot(archive)
                assert result["chiffre"] is True
        assert json.loads((root_dir / "memory.json").read_text(encoding="utf-8"))["utilisateur"] == "Carl"
        assert (root_dir / "voice_state.json").exists()

    def test_snapshot_file_size_limit_fails_before_creating_archive(self, temp_environment, mock_crypto_engine, monkeypatch):
        root_dir, mgr = temp_environment
        (root_dir / "memory.json").write_bytes(b"x" * 128)
        monkeypatch.setattr("syncsphere.snapshot.MAX_SNAPSHOT_BYTES", 64)
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            with pytest.raises(ValueError, match="taille totale"):
                mgr.creer_snapshot(nom="too_large.gos")
        assert not (mgr.snapshots_dir / "too_large.gos").exists()
        assert list(mgr.snapshots_dir.glob("*.tmp")) == []

    def test_authenticated_but_corrupt_gzip_never_changes_live_files(self, temp_environment, mock_crypto_engine):
        root_dir, mgr = temp_environment
        tar_stream = io.BytesIO()
        payload = b'{"utilisateur":"should-not-restore"}'
        metadata = json.dumps({
            "version": "1.0", "format": "gos", "timestamp": "20260101_000000",
            "fichiers": ["memory.json"], "chiffre": True, "algorithme": "AES-256-GCM",
        }).encode("utf-8")
        with tarfile.open(fileobj=tar_stream, mode="w:gz") as tar:
            for name, content in (("memory.json", payload), ("metadata.json", metadata)):
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        corrupted_gzip = bytearray(tar_stream.getvalue())
        corrupted_gzip[-1] ^= 0x01
        archive = mgr.snapshots_dir / "bad-gzip.gos"
        archive.write_bytes(mock_crypto_engine.encrypt_bytes(corrupted_gzip))

        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            with pytest.raises((OSError, EOFError, ValueError)):
                mgr.restaurer_snapshot(archive)
        assert json.loads((root_dir / "memory.json").read_text(encoding="utf-8"))["utilisateur"] == "Carl"

    def test_legacy_plaintext_snapshot_is_listed_but_never_restored_or_deleted(self, temp_environment, mock_disabled_crypto):
        """Un .gos legacy reste intact, visible, mais est fail-closed à l'import."""
        root_dir, mgr = temp_environment
        legacy = mgr.snapshots_dir / "legacy.gos"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            metadata = json.dumps({"fichiers": ["memory.json"]}).encode()
            info = tarfile.TarInfo("metadata.json")
            info.size = len(metadata)
            archive.addfile(info, io.BytesIO(metadata))
            payload = b'{"utilisateur":"ancienne"}'
            info = tarfile.TarInfo("memory.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        legacy.write_bytes(buffer.getvalue())
        original_bytes = legacy.read_bytes()

        with patch("syncsphere.snapshot.crypto_engine", mock_disabled_crypto):
            assert mgr.lister_snapshots()[0]["chiffre"] is False
            with pytest.raises(PermissionError, match="historique est en clair"):
                mgr.restaurer_snapshot(legacy)
            with pytest.raises(ValueError, match="historique en clair"):
                mgr.verifier_integrite(legacy)
            # An older caller cannot opt out of encryption enforcement.
            with pytest.raises(ValueError, match="historique en clair"):
                mgr.verifier_integrite(legacy, exiger_chiffrement=False)
        assert legacy.read_bytes() == original_bytes
        assert json.loads((root_dir / "memory.json").read_text(encoding="utf-8"))["utilisateur"] == "Carl"

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
            with pytest.raises(PermissionError, match="DataShield est verrouillé"):
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

    def test_restore_refuses_symlink_destination_before_writing(self, temp_environment, mock_crypto_engine, tmp_path):
        root_dir, mgr = temp_environment
        outside = tmp_path / "outside.json"
        outside.write_text('{"sentinel":true}', encoding="utf-8")
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            archive = mgr.creer_snapshot(nom="symlink_target.gos", chiffrer=True)
        target = root_dir / "memory.json"
        target.unlink()
        try:
            target.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("La création de liens symboliques n'est pas autorisée sur cette machine.")

        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            with pytest.raises(PermissionError, match="destination non sûre"):
                mgr.restaurer_snapshot(archive)
        assert target.is_symlink()
        assert outside.read_text(encoding="utf-8") == '{"sentinel":true}'

    def test_lister_snapshots_shows_encryption_status(self, temp_environment, mock_crypto_engine):
        """La liste distingue les archives chiffrées récentes des archives legacy."""
        root_dir, mgr = temp_environment
        with patch("syncsphere.snapshot.crypto_engine", mock_crypto_engine):
            mgr.creer_snapshot(nom="snap_1.gos", chiffrer=True)
            legacy = mgr.snapshots_dir / "snap_2.gos"
            legacy.write_bytes(b"ancienne archive en clair")

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
