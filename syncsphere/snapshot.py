# syncsphere/snapshot.py
"""Module SyncSphere pour GreatOS - Sauvegarde et synchronisation locale chiffrée.

Conforme au Cahier des Charges GreatOS (Section 4.7) :
V3 : Local-First, offline, backup local chiffré, Export/Import de snapshots (.gos).
Intégration DataShield : Chiffrement intégral AES-256-GCM et signature du format.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import time
from typing import Any, Dict, List, Optional

from datashield.crypto import BLOB_HEADER, crypto_engine

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Gère la création et la restauration de snapshots d'état GreatOS."""

    FICHIERS_CRITIQUES = [
        "memory.json",
        "memory.db",
        "goals.json",
        "voice_state.json",
    ]

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent
        self.snapshots_dir = self.root_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)

    def est_chiffre(self, chemin_snapshot: Path) -> bool:
        """Vérifie si le snapshot est chiffré avec le format DataShield AES-256-GCM."""
        if not chemin_snapshot.exists():
            return False
        try:
            with open(chemin_snapshot, "rb") as f:
                header = f.read(len(BLOB_HEADER))
                return header == BLOB_HEADER
        except Exception:
            return False

    def creer_snapshot(
        self,
        nom: Optional[str] = None,
        chiffrer: Optional[bool] = None,
    ) -> Path:
        """Crée une archive snapshot (.gos) contenant les états de mémoire et configurations.

        Si chiffrer est True (ou si chiffrer est None et que crypto_engine est actif),
        l'archive est intégralement chiffrée avec AES-256-GCM via DataShield.
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        nom_archive = nom or f"greatos_snapshot_{timestamp}.gos"
        destination = self.snapshots_dir / nom_archive

        do_encrypt = chiffrer if chiffrer is not None else crypto_engine.is_enabled
        if chiffrer is True and not crypto_engine.is_enabled:
            raise RuntimeError(
                "Impossible de chiffrer le snapshot : clé DataShield non configurée (JARVIS_CRYPTO_KEY)."
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fichiers_inclus = []

            for nom_fic in self.FICHIERS_CRITIQUES:
                src = self.root_dir / nom_fic
                if src.exists():
                    dst = tmp_path / nom_fic
                    shutil.copy2(src, dst)
                    fichiers_inclus.append(nom_fic)

            # Metadata du snapshot
            meta = {
                "version": "1.0",
                "format": "gos",
                "timestamp": timestamp,
                "fichiers": fichiers_inclus,
                "chiffre": do_encrypt,
                "algorithme": "AES-256-GCM" if do_encrypt else "none",
            }
            with open(tmp_path / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

            # Création du tar.gz temporaire
            tar_temp = tmp_path / "bundle.tar.gz"
            with tarfile.open(tar_temp, "w:gz") as tar:
                for f in tmp_path.iterdir():
                    if f.name != "bundle.tar.gz":
                        tar.add(f, arcname=f.name)

            if do_encrypt:
                tar_bytes = tar_temp.read_bytes()
                encrypted_bytes = crypto_engine.encrypt_bytes(tar_bytes)
                destination.write_bytes(encrypted_bytes)
            else:
                shutil.copy2(tar_temp, destination)

        return destination

    def restaurer_snapshot(self, chemin_snapshot: Path) -> Dict[str, Any]:
        """Restaure les fichiers d'état depuis une archive .gos (chiffrée ou non)."""
        if not chemin_snapshot.exists():
            raise FileNotFoundError(f"Snapshot introuvable : {chemin_snapshot}")

        chiffre = self.est_chiffre(chemin_snapshot)
        raw_bytes = chemin_snapshot.read_bytes()

        if chiffre:
            if not crypto_engine.is_enabled:
                raise PermissionError(
                    "Ce snapshot est chiffré (DataShield AES-256-GCM). "
                    "Définissez JARVIS_CRYPTO_KEY pour autoriser la restauration."
                )
            try:
                tar_bytes = crypto_engine.decrypt_bytes(raw_bytes, strict=True)
            except Exception as e:
                raise PermissionError(
                    f"Échec de déchiffrement du snapshot : clé incorrecte ou intégrité compromise ({e})."
                )
        else:
            tar_bytes = raw_bytes

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tar_stream = io.BytesIO(tar_bytes)
            with tarfile.open(fileobj=tar_stream, mode="r:gz") as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(path=tmp_path, filter="data")
                else:
                    tar.extractall(path=tmp_path)

            meta_file = tmp_path / "metadata.json"
            fichiers_restaures = []
            if meta_file.exists():
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    fichiers_restaures = meta.get("fichiers", [])

            for nom_fic in fichiers_restaures:
                src = tmp_path / nom_fic
                if src.exists():
                    dst = self.root_dir / nom_fic
                    shutil.copy2(src, dst)

            return {
                "succes": True,
                "fichiers_restaures": fichiers_restaures,
                "chiffre": chiffre,
            }

    def lister_snapshots(self) -> List[Dict[str, Any]]:
        """Liste tous les snapshots locaux disponibles."""
        result = []
        for p in self.snapshots_dir.glob("*.gos"):
            stat = p.stat()
            chiffre = self.est_chiffre(p)
            result.append({
                "nom": p.name,
                "taille_octets": stat.st_size,
                "chemin": str(p),
                "chiffre": chiffre,
            })
        return result


snapshot_manager = SnapshotManager()
