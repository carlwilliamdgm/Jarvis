# syncsphere/snapshot.py
"""Module SyncSphere pour GreatOS - Sauvegarde et synchronisation locale chiffrée.

Conforme au Cahier des Charges GreatOS (Section 4.7) :
V3 : Local-First, offline, backup local chiffré, Export/Import de snapshots (.gos).
Intégration DataShield : Chiffrement intégral AES-256-GCM et signature du format.
"""

from __future__ import annotations

import io
import hashlib
import gzip
import json
import logging
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import time
from typing import Any, BinaryIO, Dict, List, Optional

from datashield.crypto import BLOB_HEADER, crypto_engine
from syncsphere.secure_spool import (
    SecureSpoolError,
    SecureSpoolReader,
    SecureSpoolWriter,
    cleanup_stale_spools,
    default_spool_directory,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_SNAPSHOT_GIB = 20


def _configured_snapshot_limit_gib(value: str | None) -> int:
    try:
        limit = DEFAULT_MAX_SNAPSHOT_GIB if value is None else int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("GREATOS_MAX_SNAPSHOT_GIB doit être un entier positif.") from exc
    if limit <= 0:
        raise RuntimeError("GREATOS_MAX_SNAPSHOT_GIB doit être un entier positif.")
    return limit


MAX_SNAPSHOT_GIB = _configured_snapshot_limit_gib(os.environ.get("GREATOS_MAX_SNAPSHOT_GIB"))
MAX_SNAPSHOT_BYTES = MAX_SNAPSHOT_GIB * 1024**3
MAX_TAR_BYTES = MAX_SNAPSHOT_BYTES + 16 * 1024**2
MAX_GOS_BYTES = MAX_TAR_BYTES + 128
MAX_METADATA_BYTES = 64 * 1024
DISK_RESERVE_BYTES = 128 * 1024**2
STREAM_CHUNK_BYTES = 1024 * 1024


class _BoundedReader:
    """Count decompressed tar bytes and reject gzip expansion past its budget."""

    def __init__(self, source: BinaryIO, max_bytes: int):
        self.source = source
        self.max_bytes = max_bytes
        self.count = 0

    def _count(self, data: bytes) -> bytes:
        self.count += len(data)
        if self.count > self.max_bytes:
            raise ValueError("La taille décompressée maximale du snapshot est dépassée.")
        return data

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.max_bytes - self.count + 1
        else:
            size = min(size, self.max_bytes - self.count + 1)
        return self._count(self.source.read(size))

    def readinto(self, buffer: bytearray) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def readline(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.max_bytes - self.count + 1
        else:
            size = min(size, self.max_bytes - self.count + 1)
        return self._count(self.source.readline(size))


def _is_reparse_or_symlink(path: Path, st: os.stat_result | None = None) -> bool:
    try:
        st = st or path.lstat()
        return (
            path.is_symlink()
            or bool(getattr(path, "is_junction", lambda: False)())
            or bool(getattr(st, "st_file_attributes", 0) & 0x400)
        )
    except FileNotFoundError:
        return False
    except OSError:
        return True


class SnapshotManager:
    """Gère la création et la restauration de snapshots d'état GreatOS."""

    FICHIERS_CRITIQUES = [
        "memory.json",
        "memory.db",
        "goals.json",
        "voice_state.json",
    ]

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = Path(root_dir or Path(__file__).resolve().parent.parent).resolve(strict=True)
        if not self.root_dir.is_dir():
            raise NotADirectoryError(f"Racine GreatOS invalide : {self.root_dir}")
        self.snapshots_dir = self.root_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)
        if _is_reparse_or_symlink(self.snapshots_dir):
            raise RuntimeError("Le répertoire SyncSphere ne peut pas être un lien ou un point de réanalyse.")
        # Crash-left data is ciphertext only. Remove orphaned secure spools on
        # the next application start; active operations (live PIDs) are kept.
        try:
            cleanup_stale_spools()
        except (OSError, SecureSpoolError):
            # Spool cleanup is best effort; inaccessible temp storage must not
            # prevent GreatOS from loading unrelated capabilities.
            logger.warning("Impossible de nettoyer les spools SyncSphere résiduels.", exc_info=True)
        self._cleanup_stale_restore_files()

    def _cleanup_stale_restore_files(self) -> None:
        """Remove only old GreatOS per-file staging files left by a dead process."""
        for filename in self.FICHIERS_CRITIQUES:
            prefix = f".{filename}.greatos-restore-"
            try:
                candidates = self.root_dir.iterdir()
                for candidate in candidates:
                    if not candidate.name.startswith(prefix) or not candidate.name.endswith(".restore"):
                        continue
                    try:
                        info = candidate.lstat()
                        if _is_reparse_or_symlink(candidate, info) or not stat.S_ISREG(info.st_mode):
                            continue
                        pid_text = candidate.name[len(prefix):-len(".restore")].split("-", 1)[0]
                        if not pid_text.isdecimal() or len(pid_text) > 10:
                            continue
                        pid = int(pid_text)
                        if pid <= 0 or pid == os.getpid():
                            continue
                        try:
                            os.kill(pid, 0)
                            continue
                        except ProcessLookupError:
                            pass
                        except (PermissionError, OSError, OverflowError):
                            continue
                        candidate.unlink()
                    except OSError:
                        logger.warning("Impossible de retirer un staging SyncSphere orphelin: %s", candidate.name)
            except OSError:
                logger.warning("Impossible d’inspecter les staging SyncSphere résiduels.", exc_info=True)

    @staticmethod
    def _check_free_space(path: Path, required: int) -> None:
        try:
            free = shutil.disk_usage(path).free
        except OSError as exc:
            raise OSError("Impossible de vérifier l’espace disque pour l’opération snapshot.") from exc
        if required < 0 or free < required + DISK_RESERVE_BYTES:
            raise OSError("Espace disque insuffisant pour créer/restaurer ce snapshot en sécurité.")

    @staticmethod
    def _source_file(path: Path) -> tuple[BinaryIO, os.stat_result]:
        before = path.lstat()
        if _is_reparse_or_symlink(path, before) or not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Fichier source snapshot non régulier ou lié : {path.name}")
        source = path.open("rb")
        after = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            source.close()
            raise ValueError(f"Le fichier source snapshot a changé pendant son ouverture : {path.name}")
        return source, after

    def est_chiffre(self, chemin_snapshot: Path) -> bool:
        """Vérifie si le snapshot est chiffré avec le format DataShield AES-256-GCM."""
        if _is_reparse_or_symlink(chemin_snapshot):
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

        Le paramètre historique ``chiffrer`` est conservé pour compatibilité d'API,
        mais ``False`` est refusé : les archives en clair ne sont plus permises.
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        nom_archive = nom or f"greatos_snapshot_{timestamp}.gos"
        if Path(nom_archive).name != nom_archive or nom_archive in {".", ".."}:
            raise ValueError("Le nom du snapshot doit être un nom de fichier, sans chemin.")
        destination = self.snapshots_dir / nom_archive
        if destination.exists() or _is_reparse_or_symlink(destination):
            raise FileExistsError(f"Un snapshot portant déjà ce nom existe : {nom_archive}")

        if chiffrer is False:
            raise ValueError(
                "Les snapshots en clair sont interdits; déverrouillez DataShield pour créer un .gos chiffré."
            )
        if not crypto_engine.is_enabled:
            raise RuntimeError(
                "Impossible de créer le snapshot : DataShield est verrouillé ou sa clé est indisponible."
            )

        root = self.root_dir.resolve(strict=True)
        sources: list[tuple[str, Path, os.stat_result]] = []
        total_source_bytes = 0
        for filename in self.FICHIERS_CRITIQUES:
            source_path = root / filename
            if not source_path.exists() and not source_path.is_symlink():
                continue
            source, source_stat = self._source_file(source_path)
            source.close()
            total_source_bytes += source_stat.st_size
            if total_source_bytes > MAX_SNAPSHOT_BYTES:
                raise ValueError(f"La taille totale des données dépasse la limite SyncSphere de {MAX_SNAPSHOT_GIB} Gio.")
            sources.append((filename, source_path, source_stat))
        self._check_free_space(self.snapshots_dir, total_source_bytes + 16 * 1024**2)

        fichiers_inclus = [filename for filename, _, _ in sources]
        metadata = json.dumps({
            "version": "1.0",
            "format": "gos",
            "timestamp": timestamp,
            "fichiers": fichiers_inclus,
            "chiffre": True,
            "algorithme": "AES-256-GCM",
        }, separators=(",", ":")).encode("utf-8")
        if len(metadata) > MAX_METADATA_BYTES:
            raise ValueError("Les métadonnées dépassent la limite autorisée.")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.snapshots_dir, prefix=f".{nom_archive}.",
                suffix=".tmp", delete=False,
            ) as output:
                temp_path = Path(output.name)
                # The tar/gzip writer streams directly into DataShield: no plaintext
                # archive is staged on disk, and the .gos temp remains ciphertext.
                with crypto_engine.encrypting_writer(output, max_input_bytes=MAX_TAR_BYTES) as encrypted:
                    with tarfile.open(fileobj=encrypted, mode="w|gz") as archive:
                        for filename, source_path, initial_stat in sources:
                            source, opened_stat = self._source_file(source_path)
                            try:
                                if (opened_stat.st_size, opened_stat.st_mtime_ns) != (
                                    initial_stat.st_size, initial_stat.st_mtime_ns
                                ):
                                    raise RuntimeError(f"Le fichier source a changé avant le snapshot : {filename}")
                                info = archive.gettarinfo(fileobj=source, arcname=filename)
                                if not info.isfile():
                                    raise ValueError(f"Type de fichier source interdit : {filename}")
                                archive.addfile(info, source)
                                final_stat = os.fstat(source.fileno())
                                if (final_stat.st_size, final_stat.st_mtime_ns) != (
                                    opened_stat.st_size, opened_stat.st_mtime_ns
                                ):
                                    raise RuntimeError(f"Le fichier source a changé pendant le snapshot : {filename}")
                            finally:
                                source.close()

                        info = tarfile.TarInfo("metadata.json")
                        info.size = len(metadata)
                        info.mode = 0o600
                        archive.addfile(info, io.BytesIO(metadata))
                output.flush()
                os.fsync(output.fileno())
            # Recheck every input at the end of the capture window. This is not
            # a filesystem-wide snapshot, but detects writes to an early file
            # while later files were being serialized.
            for filename, source_path, initial_stat in sources:
                current_stat = source_path.stat(follow_symlinks=False)
                if (current_stat.st_size, current_stat.st_mtime_ns, current_stat.st_ino) != (
                    initial_stat.st_size, initial_stat.st_mtime_ns, initial_stat.st_ino
                ):
                    raise RuntimeError(f"Le fichier source a changé pendant le snapshot : {filename}")

            final_stat = temp_path.stat()
            if final_stat.st_size > MAX_GOS_BYTES or not self.est_chiffre(temp_path):
                raise RuntimeError("Le blob snapshot final dépasse sa limite ou n’est pas chiffré DataShield.")
            if destination.exists() or _is_reparse_or_symlink(destination):
                raise FileExistsError(f"Un snapshot portant déjà ce nom existe : {nom_archive}")
            # os.rename fails rather than replacing an existing file on Windows.
            os.rename(temp_path, destination)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        return destination

    def _open_encrypted_snapshot(self, path: Path) -> tuple[BinaryIO, int]:
        try:
            before = path.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(f"Snapshot introuvable : {path}")
        if _is_reparse_or_symlink(path, before) or not stat.S_ISREG(before.st_mode):
            raise PermissionError("Lecture refusée : le chemin snapshot n’est pas un fichier régulier local.")
        if before.st_size > MAX_GOS_BYTES:
            raise ValueError(f"La taille chiffrée du snapshot dépasse la limite SyncSphere de {MAX_SNAPSHOT_GIB} Gio.")
        if before.st_size < 4 + 1 + 16 + 12 + 16:
            raise ValueError("Blob DataShield tronqué.")
        stream = path.open("rb")
        after = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            stream.close()
            raise RuntimeError("Le snapshot a changé pendant son ouverture.")
        if stream.read(len(BLOB_HEADER)) != BLOB_HEADER:
            stream.close()
            raise ValueError(
                "Snapshot historique en clair détecté; vérification et restauration refusées. "
                "L’archive est conservée sans modification."
            )
        stream.seek(0)
        return stream, after.st_size

    def _inspect_tar_stream(
        self,
        source: BinaryIO,
        staging_spools: dict[str, Path] | None = None,
    ) -> tuple[List[str], int]:
        gzip_stream = gzip.GzipFile(fileobj=source, mode="rb")
        bounded_stream = _BoundedReader(gzip_stream, MAX_TAR_BYTES)
        metadata_bytes: bytes | None = None
        filenames: list[str] = []
        total_file_bytes = 0
        seen: set[str] = set()
        try:
            with tarfile.open(fileobj=bounded_stream, mode="r|") as archive:
                for member in archive:
                    if (
                        member.name in seen
                        or member.name not in {*self.FICHIERS_CRITIQUES, "metadata.json"}
                        or not member.isfile()
                        or Path(member.name).name != member.name
                        or "\\" in member.name
                        or member.size < 0
                    ):
                        raise ValueError("Le snapshot contient un chemin ou un type de fichier interdit.")
                    seen.add(member.name)
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError("Entrée du snapshot illisible.")
                    if member.name == "metadata.json":
                        if member.size > MAX_METADATA_BYTES:
                            raise ValueError("Les métadonnées dépassent la limite autorisée.")
                        metadata_bytes = extracted.read(MAX_METADATA_BYTES + 1)
                        if len(metadata_bytes) != member.size or len(metadata_bytes) > MAX_METADATA_BYTES:
                            raise ValueError("Métadonnées du snapshot tronquées ou trop volumineuses.")
                        continue

                    total_file_bytes += member.size
                    if total_file_bytes > MAX_SNAPSHOT_BYTES:
                        raise ValueError(f"La taille totale des données dépasse la limite SyncSphere de {MAX_SNAPSHOT_GIB} Gio.")
                    filenames.append(member.name)
                    writer = None
                    if staging_spools is not None:
                        self._check_free_space(default_spool_directory(), member.size + 128)
                        writer = SecureSpoolWriter.create(max_bytes=max(1, member.size))
                        staging_spools[member.name] = writer.path
                    output = writer
                    completed = False
                    try:
                        copied = 0
                        while copied < member.size:
                            chunk = extracted.read(min(STREAM_CHUNK_BYTES, member.size - copied))
                            if not chunk:
                                raise ValueError(f"Donnée tronquée dans le snapshot : {member.name}")
                            if output is not None:
                                output.write(chunk)
                            copied += len(chunk)
                        completed = True
                    finally:
                        if writer is not None:
                            if completed:
                                writer.close()
                            else:
                                writer.abort()

            # Tar may stop at its end markers before gzip's checksum/trailer.
            # Drain it so gzip CRC and the decompressed-size budget are checked.
            while bounded_stream.read(STREAM_CHUNK_BYTES):
                pass
        finally:
            gzip_stream.close()

        if metadata_bytes is None or "metadata.json" not in seen:
            raise ValueError("Le snapshot ne contient pas ses métadonnées.")
        try:
            metadata = json.loads(metadata_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Les métadonnées du snapshot sont invalides.") from exc
        if not isinstance(metadata, dict):
            raise ValueError("Les métadonnées du snapshot sont invalides.")
        declared = metadata.get("fichiers")
        if (
            metadata.get("chiffre") is not True
            or metadata.get("algorithme") != "AES-256-GCM"
            or not isinstance(declared, list)
            or any(not isinstance(name, str) for name in declared)
            or len(declared) != len(set(declared))
            or len(declared) != len(filenames)
            or set(declared) != set(filenames)
        ):
            raise ValueError("Les fichiers déclarés dans les métadonnées sont absents ou incohérents.")
        return filenames, total_file_bytes

    def verifier_integrite(self, chemin_snapshot: Path, exiger_chiffrement: bool = True) -> Dict[str, Any]:
        """Vérifie AES-GCM, gzip et tar à mémoire bornée (format DataShield historique)."""
        source, source_size = self._open_encrypted_snapshot(chemin_snapshot)
        if not crypto_engine.is_enabled:
            source.close()
            raise PermissionError("DataShield doit être déverrouillé pour vérifier ce snapshot.")
        self._check_free_space(Path(tempfile.gettempdir()), source_size)
        spool_path: Path | None = None
        try:
            with source, SecureSpoolWriter.create(max_bytes=MAX_TAR_BYTES) as decrypted:
                spool_path = decrypted.path
                crypto_engine.decrypt_stream(
                    source, decrypted, max_input_bytes=MAX_GOS_BYTES, max_output_bytes=MAX_TAR_BYTES
                )
            with SecureSpoolReader(spool_path, max_bytes=MAX_TAR_BYTES) as decrypted:
                filenames, _ = self._inspect_tar_stream(decrypted)
        finally:
            if spool_path is not None:
                try:
                    spool_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Impossible de nettoyer le spool chiffré de validation du snapshot.")
        return {"succes": True, "chiffre": True, "fichiers_verifies": filenames}

    def supprimer_snapshot_cree(self, chemin_snapshot: Path, empreinte_attendue: str) -> None:
        """Supprime uniquement le snapshot créé par l'opération compensée et resté inchangé."""
        destination = chemin_snapshot.resolve()
        snapshots_dir = self.snapshots_dir.resolve()
        if destination.parent != snapshots_dir or destination.suffix.lower() != ".gos":
            raise ValueError("Refus de supprimer un fichier extérieur au dépôt des snapshots.")
        hasher = hashlib.sha256()
        with destination.open("rb") as fichier:
            for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
                hasher.update(bloc)
        empreinte = hasher.hexdigest()
        if empreinte != empreinte_attendue:
            raise RuntimeError("Le snapshot a changé depuis sa création; compensation refusée.")
        destination.unlink()

    def restaurer_snapshot(self, chemin_snapshot: Path) -> Dict[str, Any]:
        """Restaure uniquement une archive .gos authentifiée et chiffrée AES-256-GCM."""
        if not _is_reparse_or_symlink(chemin_snapshot) and not self.est_chiffre(chemin_snapshot):
            raise PermissionError(
                "Restauration refusée : ce snapshot historique est en clair. "
                "Il est conservé intact, mais SyncSphere n’importe que des snapshots chiffrés AES-256-GCM."
            )
        source, source_size = self._open_encrypted_snapshot(chemin_snapshot)
        if not crypto_engine.is_enabled:
            source.close()
            raise PermissionError(
                "Ce snapshot est chiffré (DataShield AES-256-GCM), mais DataShield est verrouillé."
            )
        root = self.root_dir.resolve(strict=True)
        root_staged: dict[str, Path] = {}
        secure_staged: dict[str, Path] = {}
        decrypted_spool_path: Path | None = None
        try:
            spool_dir = default_spool_directory()
            spool_dir.mkdir(parents=True, exist_ok=True)
            self._check_free_space(spool_dir, source_size + DISK_RESERVE_BYTES)
            with source, SecureSpoolWriter.create(max_bytes=MAX_TAR_BYTES) as decrypted:
                decrypted_spool_path = decrypted.path
                try:
                    crypto_engine.decrypt_stream(
                        source, decrypted, max_input_bytes=MAX_GOS_BYTES,
                        max_output_bytes=MAX_TAR_BYTES,
                    )
                except Exception as exc:
                    raise PermissionError(
                        f"Échec de déchiffrement du snapshot : clé incorrecte ou intégrité compromise ({exc})."
                    ) from exc

            # Inspect first, without extracting; reserve disk before creating any
            # staged state files. A second streaming pass writes the validated set.
            with SecureSpoolReader(decrypted_spool_path, max_bytes=MAX_TAR_BYTES) as archive_stream:
                filenames, total_bytes = self._inspect_tar_stream(archive_stream)
            self._check_free_space(root, total_bytes)
            with SecureSpoolReader(decrypted_spool_path, max_bytes=MAX_TAR_BYTES) as archive_stream:
                staged_names, staged_bytes = self._inspect_tar_stream(archive_stream, staging_spools=secure_staged)
            if staged_names != filenames or staged_bytes != total_bytes:
                raise RuntimeError("Le snapshot a changé entre ses passes de validation.")

            # No live profile file is replaced until the complete authenticated
            # archive has passed both bounded validation passes.
            destinations: dict[str, Path] = {}
            for filename in filenames:
                destination = root / filename
                if destination.parent != root or _is_reparse_or_symlink(destination):
                    raise PermissionError(f"Restauration refusée : destination non sûre pour {filename}.")
                destinations[filename] = destination

            # Copy all validated files to same-volume temporary entries first;
            # only then atomically replace live files one by one.
            for filename in filenames:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=root,
                    prefix=f".{filename}.greatos-restore-{os.getpid()}-", suffix=".restore", delete=False,
                ) as output:
                    root_staged[filename] = Path(output.name)
                    with SecureSpoolReader(secure_staged[filename], max_bytes=MAX_SNAPSHOT_BYTES) as input_file:
                        shutil.copyfileobj(input_file, output, length=STREAM_CHUNK_BYTES)
                    output.flush()
                    os.fsync(output.fileno())

            for filename in filenames:
                destination = destinations[filename]
                if _is_reparse_or_symlink(destination):
                    raise PermissionError(f"La destination a changé pendant la restauration : {filename}.")
                os.replace(root_staged[filename], destination)
                root_staged.pop(filename)

            return {"succes": True, "fichiers_restaures": filenames, "chiffre": True}
        finally:
            for staged in root_staged.values():
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    logger.error("Impossible de nettoyer un staging de restauration SyncSphere.")
            for staged in secure_staged.values():
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Impossible de nettoyer un spool chiffré SyncSphere.")
            if decrypted_spool_path is not None:
                try:
                    decrypted_spool_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Impossible de nettoyer le spool chiffré du snapshot.")

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
