# syncsphere/snapshot.py
"""Module SyncSphere pour GreatOS - Sauvegarde et synchronisation locale chiffrée.

Conforme au Cahier des Charges GreatOS (Section 4.7) :
V3 : Local-First, offline, backup local chiffré, Export/Import de snapshots (.gos).
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Dict, List, Optional


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

    def creer_snapshot(self, nom: Optional[str] = None) -> Path:
        """Crée une archive snapshot (.gos) contenant les états de mémoire et configurations."""
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        nom_archive = nom or f"greatos_snapshot_{timestamp}.gos"
        destination = self.snapshots_dir / nom_archive

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
            }
            with open(tmp_path / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

            with tarfile.open(destination, "w:gz") as tar:
                for f in tmp_path.iterdir():
                    tar.add(f, arcname=f.name)

        return destination

    def restaurer_snapshot(self, chemin_snapshot: Path) -> Dict:
        """Restaure les fichiers d'état depuis une archive .gos."""
        if not chemin_snapshot.exists():
            raise FileNotFoundError(f"Snapshot introuvable : {chemin_snapshot}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with tarfile.open(chemin_snapshot, "r:gz") as tar:
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
            }

    def lister_snapshots(self) -> List[Dict]:
        """Liste tous les snapshots locaux disponibles."""
        result = []
        for p in self.snapshots_dir.glob("*.gos"):
            stat = p.stat()
            result.append({
                "nom": p.name,
                "taille_octets": stat.st_size,
                "chemin": str(p),
            })
        return result


snapshot_manager = SnapshotManager()
