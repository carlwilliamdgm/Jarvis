"""Windows CurrentUser DPAPI store for the DataShield master secret.

This module protects a secret at rest with the Windows user profile DPAPI.
The application may gate calls to it behind Windows Hello, but DPAPI itself is
not cryptographically bound to Hello; native Hello key wrapping is a separate
requirement when a process-level cryptographic boundary is needed.
"""

from __future__ import annotations

import ctypes
import hmac
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

_MAGIC = b"GREATOS-DPAPI\x01"
_MAX_SECRET_BYTES = 64 * 1024
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class KeyStoreError(RuntimeError):
    """A fail-closed error while protecting or reading the local key store."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _require_windows() -> None:
    if os.name != "nt":
        raise KeyStoreError("Le key store DPAPI est disponible uniquement sous Windows.")


def key_store_path() -> Path:
    """Return configured path or the per-user GreatOS default path."""
    configured = os.environ.get("GREATOS_KEY_STORE_PATH")
    if configured is not None:
        if not configured.strip():
            raise KeyStoreError("GREATOS_KEY_STORE_PATH ne peut pas être vide.")
        path = Path(os.path.expandvars(configured)).expanduser()
        if not path.is_absolute():
            raise KeyStoreError("GREATOS_KEY_STORE_PATH doit être un chemin absolu.")
        return path

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data or not local_app_data.strip():
        raise KeyStoreError("LOCALAPPDATA est requis pour le chemin DPAPI par défaut.")
    base = Path(os.path.expandvars(local_app_data)).expanduser()
    if not base.is_absolute():
        raise KeyStoreError("LOCALAPPDATA doit être un chemin absolu.")
    return base / "GreatOS" / "DataShield" / "master-key.dpapi"


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    """Invoke DPAPI for the current Windows user, without UI or extra entropy."""
    _require_windows()
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        transform = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        transform.argtypes = (
            [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
            if protect else
            [ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
             ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
             wintypes.DWORD, ctypes.POINTER(_DataBlob)]
        )
        transform.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        source_buffer = ctypes.create_string_buffer(data, len(data))
        source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        result = _DataBlob()
        description = wintypes.LPWSTR()
        if protect:
            ok = transform(ctypes.byref(source), "GreatOS DataShield master key", None,
                           None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result))
        else:
            ok = transform(ctypes.byref(source), ctypes.byref(description), None,
                           None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result))
        if not ok:
            raise KeyStoreError("DPAPI a refusé l'opération.")
        if not result.pbData or result.cbData == 0:
            raise KeyStoreError("DPAPI a retourné un résultat vide.")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(result.pbData)
            if description:
                kernel32.LocalFree(description)
    except KeyStoreError:
        raise
    except Exception as exc:
        raise KeyStoreError("Échec DPAPI; aucune donnée en clair n'a été utilisée.") from exc


def _resolve_path(path: Path | None) -> Path:
    resolved = key_store_path() if path is None else Path(path)
    if not resolved.is_absolute():
        raise KeyStoreError("Le chemin du key store doit être absolu.")
    return resolved


def _validate_secret(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret:
        raise KeyStoreError("Le secret doit être une chaîne UTF-8 non vide.")
    try:
        encoded = secret.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise KeyStoreError("Le secret n'est pas encodable en UTF-8.") from exc
    if len(encoded) > _MAX_SECRET_BYTES or b"\x00" in encoded:
        raise KeyStoreError("Le secret dépasse la limite ou contient un octet nul.")
    return encoded


def protect_secret(secret: str, path: Path | None = None) -> Path:
    """Protect a UTF-8 secret using DPAPI CurrentUser and atomically persist it.

    The temporary file is created in the destination directory so Windows
    inherits the directory ACL; replacement is atomic on the same volume.
    """
    _require_windows()
    destination = _resolve_path(path)
    plaintext = _validate_secret(secret)
    protected = _MAGIC + _dpapi_transform(plaintext, protect=True)
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp",
                                    dir=str(destination.parent))
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(protected)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
        return destination
    except Exception as exc:
        raise KeyStoreError("Impossible d'écrire atomiquement le key store DPAPI.") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def unprotect_secret(path: Path | None = None) -> str:
    """Read and decrypt a DPAPI CurrentUser-protected UTF-8 secret."""
    _require_windows()
    source = _resolve_path(path)
    try:
        if source.is_symlink():
            raise KeyStoreError("Le key store ne peut pas être un lien symbolique.")
        payload = source.read_bytes()
    except KeyStoreError:
        raise
    except OSError as exc:
        raise KeyStoreError("Impossible de lire le key store DPAPI.") from exc
    if not payload.startswith(_MAGIC) or len(payload) <= len(_MAGIC):
        raise KeyStoreError("Format de key store DPAPI invalide.")
    clear = _dpapi_transform(payload[len(_MAGIC):], protect=False)
    if not clear or len(clear) > _MAX_SECRET_BYTES or b"\x00" in clear:
        raise KeyStoreError("Le secret déchiffré ne respecte pas le format attendu.")
    try:
        return clear.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise KeyStoreError("Le secret déchiffré n'est pas un UTF-8 valide.") from exc


def verify_secret(secret: str, path: Path | None = None) -> bool:
    """Return whether the protected value equals ``secret``; errors fail closed."""
    try:
        expected = _validate_secret(secret)
        actual = _validate_secret(unprotect_secret(path))
        return hmac.compare_digest(expected, actual)
    except (KeyStoreError, TypeError, ValueError):
        return False


def recovery_check_path(path: Path | None = None) -> Path:
    """Return the authenticated recovery verifier paired with the DPAPI store."""
    return _resolve_path(path).with_name("master-key.check")


def ensure_recovery_check(secret: str, path: Path | None = None) -> Path:
    """Create an AES-GCM recovery verifier, or verify an existing one unchanged."""
    _require_windows()
    secret_bytes = _validate_secret(secret)
    verifier_path = recovery_check_path(path)
    marker = "GreatOS DataShield recovery key verifier v1"
    if verifier_path.exists():
        if not verify_recovery_secret(secret, path):
            raise KeyStoreError("Le vérificateur de récupération existant ne correspond pas à la clé.")
        return verifier_path

    try:
        _write_recovery_check(marker, secret_bytes, verifier_path, replace=False)
        return verifier_path
    except KeyStoreError:
        raise
    except Exception as exc:
        raise KeyStoreError("Impossible de créer le vérificateur de récupération DataShield.") from exc


def verify_recovery_secret(secret: str, path: Path | None = None) -> bool:
    """Authenticate the manual key against the AES-GCM recovery verifier."""
    try:
        secret_bytes = _validate_secret(secret)
        verifier_path = recovery_check_path(path)
        if verifier_path.is_symlink():
            return False
        from datashield.crypto import decrypt_str
        actual = decrypt_str(verifier_path.read_text(encoding="ascii"), secret_bytes)
        return hmac.compare_digest(actual, "GreatOS DataShield recovery key verifier v1")
    except Exception:
        return False


def _write_recovery_check(marker: str, secret_bytes: bytes, verifier_path: Path,
                          *, replace: bool) -> None:
    from datashield.crypto import encrypt_str
    payload = encrypt_str(marker, secret_bytes)
    verifier_path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{verifier_path.name}.", suffix=".tmp",
                                dir=str(verifier_path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, verifier_path)
        else:
            # Windows rename is atomic and refuses to replace an existing path.
            try:
                os.rename(temporary, verifier_path)
            except OSError:
                if not verifier_path.exists():
                    raise
                raise KeyStoreError("Un vérificateur de récupération concurrent existe déjà.")
    finally:
        temporary.unlink(missing_ok=True)


def restore_secret_store(secret: str, path: Path | None = None) -> bool:
    """Validate the manual key and atomically rebuild a missing/corrupt DPAPI blob."""
    destination = _resolve_path(path)
    if verify_secret(secret, destination):
        if verify_recovery_secret(secret, destination):
            return True
        try:
            ensure_recovery_check(secret, destination)
        except KeyStoreError:
            # The DPAPI copy independently validated the manual key, so it is
            # safe to repair an absent or damaged recovery verifier from it.
            _write_recovery_check("GreatOS DataShield recovery key verifier v1",
                                  _validate_secret(secret), recovery_check_path(destination),
                                  replace=True)
        return True
    if not verify_recovery_secret(secret, destination):
        return False
    protect_secret(secret, destination)
    return True
