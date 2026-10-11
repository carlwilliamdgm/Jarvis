"""Stockage local atomique et chiffré des données propres à un utilisateur."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from datashield.crypto import crypto_engine


ENCRYPTED_JSON_KEY = "__greatos_encrypted_json_v1__"
_STORE_LOCK = threading.RLock()


def _require_encryption() -> None:
    if not crypto_engine.is_enabled:
        raise RuntimeError("Stockage utilisateur refusé : chiffrement DataShield indisponible.")


def _decode_envelope(value: Any) -> Any:
    if not isinstance(value, dict) or set(value) != {ENCRYPTED_JSON_KEY}:
        raise RuntimeError("Enveloppe de données utilisateur chiffrée invalide.")
    blob = value[ENCRYPTED_JSON_KEY]
    if not isinstance(blob, str):
        raise RuntimeError("Enveloppe de données utilisateur chiffrée invalide.")
    _require_encryption()
    try:
        return json.loads(crypto_engine.decrypt(blob, strict=True))
    except Exception as exc:
        raise RuntimeError("Données utilisateur chiffrées illisibles; lecture refusée.") from exc


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f"{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def save_encrypted_json(path: Path, value: Any) -> None:
    """Chiffre et remplace atomiquement un document JSON utilisateur."""
    _require_encryption()
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    envelope = {ENCRYPTED_JSON_KEY: crypto_engine.encrypt(encoded)}
    with _STORE_LOCK:
        _atomic_write_json(path, envelope)


def load_encrypted_json(path: Path, default_factory: Callable[[], Any]) -> Any:
    """Lit un document chiffré; migre atomiquement un ancien JSON en clair."""
    with _STORE_LOCK:
        _require_encryption()
        if not path.exists():
            return default_factory()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Données utilisateur illisibles; lecture refusée.") from exc

        if isinstance(raw, dict) and ENCRYPTED_JSON_KEY in raw:
            return _decode_envelope(raw)
        if isinstance(raw, dict) and any(key.startswith("__greatos_encrypted_") for key in raw):
            raise RuntimeError("Format de chiffrement des données utilisateur non reconnu.")

        _require_encryption()
        # Un format historique valide n'est retourné qu'après la migration
        # atomique : une erreur de chiffrement ne laisse pas le système lire
        # durablement ces données en clair.
        _atomic_write_json(path, {ENCRYPTED_JSON_KEY: crypto_engine.encrypt(
            json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        )})
        return raw


def _encode_jsonl_record(value: Any) -> str:
    _require_encryption()
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({ENCRYPTED_JSON_KEY: crypto_engine.encrypt(serialized)}, ensure_ascii=False)


def _migrate_jsonl_locked(path: Path) -> list[str]:
    if not path.exists():
        return []
    existing = path.read_text(encoding="utf-8").splitlines()
    migrated_lines: list[str] = []
    needs_migration = False
    for line in existing:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Journal utilisateur illisible; écriture refusée.") from exc
        if isinstance(entry, dict) and ENCRYPTED_JSON_KEY in entry:
            _decode_envelope(entry)
            migrated_lines.append(line)
        else:
            if isinstance(entry, dict) and any(key.startswith("__greatos_encrypted_") for key in entry):
                raise RuntimeError("Format de chiffrement du journal utilisateur non reconnu.")
            migrated_lines.append(_encode_jsonl_record(entry))
            needs_migration = True

    if needs_migration:
        content = "\n".join(migrated_lines) + ("\n" if migrated_lines else "")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent,
                prefix=f"{path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
    return migrated_lines


def migrate_encrypted_jsonl(path: Path) -> None:
    """Migre sans ajout les anciens enregistrements JSONL vers le chiffrement."""
    with _STORE_LOCK:
        _require_encryption()
        _migrate_jsonl_locked(path)


def append_encrypted_jsonl(path: Path, value: Any) -> None:
    """Ajoute une entrée JSONL chiffrée et migre d'abord les lignes legacy."""
    with _STORE_LOCK:
        _require_encryption()
        path.parent.mkdir(parents=True, exist_ok=True)
        _migrate_jsonl_locked(path)
        encoded = _encode_jsonl_record(value)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
