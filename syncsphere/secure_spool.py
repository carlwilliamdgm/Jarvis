"""Authenticated, DPAPI-wrapped temporary spools for Windows-only plaintext staging.

The spool file itself contains ciphertext only. Each file has a fresh AES-256
key protected by Windows DPAPI CurrentUser, and each bounded frame has its own
AES-GCM tag. Consumers must finish the reader context successfully before
publishing any output: per-frame authentication does not prove that later
frames or the stream terminator are present.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import struct
import tempfile
from typing import Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from datashield import windows_key_store

MAGIC = b"GSSPOOL1"
VERSION = 1
CHUNK_BYTES = 1024 * 1024
MAX_WRAPPED_KEY_BYTES = 16 * 1024
DEFAULT_MAX_SPOOL_BYTES = 20 * 1024**3 + 16 * 1024**2
_FIXED_HEADER = struct.Struct(">8sB16s4sI")
_FRAME_HEADER = struct.Struct(">QI")
_TAG_BYTES = 16
_SPOOL_NAME = re.compile(r"^greatos-spool-(\d{1,10})-[0-9a-f]{32}\.gsspool$")


class SecureSpoolError(RuntimeError):
    """Invalid, incomplete, unavailable, or oversized secure spool."""


def default_spool_directory() -> Path:
    """Return GreatOS's dedicated temporary spool directory."""
    return Path(tempfile.gettempdir()) / "GreatOS" / "SecureSpool"


def _require_windows() -> None:
    windows_key_store._require_windows()


def _wrap_key(key: bytes) -> bytes:
    _require_windows()
    try:
        wrapped = windows_key_store._dpapi_transform(key, protect=True)
    except Exception as exc:
        raise SecureSpoolError("DPAPI n'a pas pu protéger la clé temporaire.") from exc
    if not wrapped or len(wrapped) > MAX_WRAPPED_KEY_BYTES:
        raise SecureSpoolError("La clé temporaire protégée DPAPI a un format invalide.")
    return wrapped


def _unwrap_key(wrapped: bytes) -> bytes:
    _require_windows()
    try:
        key = windows_key_store._dpapi_transform(wrapped, protect=False)
    except Exception as exc:
        raise SecureSpoolError("DPAPI n'a pas pu déverrouiller la clé temporaire.") from exc
    if len(key) != 32:
        raise SecureSpoolError("La clé temporaire DPAPI n'est pas une clé AES-256.")
    return key


def _check_regular_file(path: Path) -> os.stat_result:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SecureSpoolError("Impossible d'inspecter le spool temporaire.") from exc
    attrs = getattr(before, "st_file_attributes", 0)
    if path.is_symlink() or attrs & 0x400 or not path.is_file():
        raise SecureSpoolError("Le spool temporaire doit être un fichier régulier sans lien.")
    return before


def _aad(header_digest: bytes, frame_header: bytes) -> bytes:
    return header_digest + frame_header


class SecureSpoolWriter:
    """Write bounded AES-GCM frames to a ciphertext-only file."""

    def __init__(self, path: Path, *, max_bytes: int = DEFAULT_MAX_SPOOL_BYTES):
        _require_windows()
        if max_bytes <= 0:
            raise ValueError("max_bytes doit être positif.")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._written = 0
        self._sequence = 0
        self._closed = False
        self._pending = bytearray()
        key = secrets.token_bytes(32)
        spool_id = secrets.token_bytes(16)
        nonce_prefix = secrets.token_bytes(4)
        wrapped = _wrap_key(key)
        fixed = _FIXED_HEADER.pack(MAGIC, VERSION, spool_id, nonce_prefix, len(wrapped))
        self._header_digest = hashlib.sha256(fixed + wrapped).digest()
        self._key = key
        self._nonce_prefix = nonce_prefix
        self._cipher = AESGCM(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or getattr(self.path.parent, "is_junction", lambda: False)():
            raise SecureSpoolError("Le dossier de spool ne peut pas être un lien ou point de réanalyse.")
        try:
            self._stream = self.path.open("xb")
            self._stream.write(fixed)
            self._stream.write(wrapped)
        except Exception:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @classmethod
    def create(
        cls,
        directory: Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_SPOOL_BYTES,
    ) -> "SecureSpoolWriter":
        _require_windows()
        target = Path(directory) if directory is not None else default_spool_directory()
        target.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
            raise SecureSpoolError("Le dossier de spool ne peut pas être un lien ou point de réanalyse.")
        name = f"greatos-spool-{os.getpid()}-{secrets.token_hex(16)}.gsspool"
        return cls(target / name, max_bytes=max_bytes)

    @property
    def bytes_written(self) -> int:
        return self._written

    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return not self._closed

    def flush(self) -> None:
        """Flush encrypted frames already emitted to the underlying file."""
        if self._closed:
            raise ValueError("Le spool est fermé.")
        self._stream.flush()

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if self._closed:
            raise ValueError("Le spool est fermé.")
        view = memoryview(data).cast("B")
        total = view.nbytes
        if self._written + total > self.max_bytes:
            raise SecureSpoolError("La limite de données du spool temporaire est dépassée.")
        self._written += total
        offset = 0
        while offset < total:
            take = min(CHUNK_BYTES - len(self._pending), total - offset)
            self._pending.extend(view[offset:offset + take])
            offset += take
            if len(self._pending) == CHUNK_BYTES:
                self._write_frame(bytes(self._pending))
                self._pending.clear()
        return total

    def _write_frame(self, plaintext: bytes) -> None:
        size = len(plaintext)
        frame = _FRAME_HEADER.pack(self._sequence, size)
        nonce = self._nonce_prefix + struct.pack(">Q", self._sequence)
        encrypted = self._cipher.encrypt(nonce, plaintext, _aad(self._header_digest, frame))
        self._stream.write(frame)
        self._stream.write(encrypted)
        self._sequence += 1

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._pending:
                self._write_frame(bytes(self._pending))
                self._pending.clear()
            frame = _FRAME_HEADER.pack(self._sequence, 0)
            nonce = self._nonce_prefix + struct.pack(">Q", self._sequence)
            tag = self._cipher.encrypt(nonce, b"", _aad(self._header_digest, frame))
            self._stream.write(frame)
            self._stream.write(tag)
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except BaseException:
            self.abort()
            raise
        else:
            self._stream.close()
            self._closed = True
            self._key = b""
            self._cipher = None

    def abort(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True
            self._key = b""
            self._cipher = None
            self._pending.clear()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "SecureSpoolWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.close()
        else:
            self.abort()
        return False


class SecureSpoolReader:
    """Sequential bounded reader; successful context exit validates stream end."""

    def __init__(self, path: Path, *, max_bytes: int = DEFAULT_MAX_SPOOL_BYTES):
        _require_windows()
        if max_bytes <= 0:
            raise ValueError("max_bytes doit être positif.")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._read_bytes = 0
        self._sequence = 0
        self._buffer = bytearray()
        self._ended = False
        self._closed = False
        self.verified = False
        before = _check_regular_file(self.path)
        try:
            max_chunks = (max_bytes + CHUNK_BYTES - 1) // CHUNK_BYTES
            maximum_file_size = (
                _FIXED_HEADER.size + MAX_WRAPPED_KEY_BYTES + max_bytes
                + (max_chunks + 1) * (_FRAME_HEADER.size + _TAG_BYTES)
            )
            if before.st_size > maximum_file_size:
                raise SecureSpoolError("Le fichier spool dépasse sa taille maximale structurelle.")
            self._stream = self.path.open("rb")
            after = os.fstat(self._stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
                raise SecureSpoolError("Le spool temporaire a changé pendant son ouverture.")
            fixed = self._stream.read(_FIXED_HEADER.size)
            if len(fixed) != _FIXED_HEADER.size:
                raise SecureSpoolError("En-tête du spool temporaire tronqué.")
            magic, version, _spool_id, nonce_prefix, wrapped_len = _FIXED_HEADER.unpack(fixed)
            if magic != MAGIC or version != VERSION or not 1 <= wrapped_len <= MAX_WRAPPED_KEY_BYTES:
                raise SecureSpoolError("Format de spool temporaire inconnu ou invalide.")
            wrapped = self._stream.read(wrapped_len)
            if len(wrapped) != wrapped_len:
                raise SecureSpoolError("Clé DPAPI du spool temporaire tronquée.")
            exact_maximum = (
                _FIXED_HEADER.size + wrapped_len + max_bytes
                + (max_chunks + 1) * (_FRAME_HEADER.size + _TAG_BYTES)
            )
            if after.st_size > exact_maximum:
                raise SecureSpoolError("Le fichier spool dépasse sa taille maximale structurelle.")
            self._key = _unwrap_key(wrapped)
            self._cipher = AESGCM(self._key)
            self._nonce_prefix = nonce_prefix
            self._header_digest = hashlib.sha256(fixed + wrapped).digest()
        except Exception:
            if hasattr(self, "_stream"):
                self._stream.close()
            raise

    def _next_frame(self, *, keep_plaintext: bool = True) -> bool:
        frame = self._stream.read(_FRAME_HEADER.size)
        if not frame:
            raise SecureSpoolError("Le spool temporaire ne contient pas de fin authentifiée.")
        if len(frame) != _FRAME_HEADER.size:
            raise SecureSpoolError("En-tête de bloc du spool tronqué.")
        sequence, size = _FRAME_HEADER.unpack(frame)
        if sequence != self._sequence or size > CHUNK_BYTES:
            raise SecureSpoolError("Séquence ou taille de bloc invalide dans le spool.")
        encrypted_size = size + _TAG_BYTES
        encrypted = self._stream.read(encrypted_size)
        if len(encrypted) != encrypted_size:
            raise SecureSpoolError("Bloc chiffré du spool tronqué.")
        nonce = self._nonce_prefix + struct.pack(">Q", sequence)
        try:
            plaintext = self._cipher.decrypt(nonce, encrypted, _aad(self._header_digest, frame))
        except InvalidTag as exc:
            raise SecureSpoolError("Authentification AES-GCM du spool échouée.") from exc
        self._sequence += 1
        if size == 0:
            if plaintext or self._stream.read(1):
                raise SecureSpoolError("Données inattendues après la fin du spool.")
            self._ended = True
            self.verified = True
            return False
        if len(plaintext) != size or self._read_bytes + size > self.max_bytes:
            raise SecureSpoolError("Le spool dépasse la limite de données autorisée.")
        self._read_bytes += size
        if keep_plaintext:
            self._buffer.extend(plaintext)
        return True

    def read(self, size: int = -1) -> bytes:
        if self._closed:
            raise ValueError("Le spool est fermé.")
        # Never let a single call allocate more than one frame, even for read(-1).
        target = CHUNK_BYTES if size < 0 else min(size, CHUNK_BYTES)
        if target < 0:
            raise ValueError("Taille de lecture invalide.")
        while len(self._buffer) < target and not self._ended:
            self._next_frame()
        count = min(target, len(self._buffer))
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def readinto(self, buffer: bytearray | memoryview) -> int:
        view = memoryview(buffer)
        chunk = self.read(min(len(view), CHUNK_BYTES))
        view[:len(chunk)] = chunk
        return len(chunk)

    def iter_chunks(self) -> Iterator[bytes]:
        while True:
            chunk = self.read(CHUNK_BYTES)
            if not chunk:
                return
            yield chunk

    def verify_complete(self) -> None:
        """Drain unread data and require an authenticated terminator and EOF."""
        while not self._ended:
            self._next_frame(keep_plaintext=False)
        if self._buffer:
            # The buffered bytes were already authenticated; clear them on final close.
            self._buffer.clear()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.verify_complete()
        finally:
            self._stream.close()
            self._closed = True
            self._key = b""
            self._cipher = None
            self._buffer.clear()

    def __enter__(self) -> "SecureSpoolReader":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.close()
        else:
            self._stream.close()
            self._closed = True
            self._key = b""
            self._cipher = None
            self._buffer.clear()
        return False


def cleanup_stale_spools(directory: Path | None = None) -> list[Path]:
    """Remove abandoned GreatOS spool files whose creating PID is no longer alive.

    Only direct children matching the helper's private filename convention are
    considered. Live-process spools, directories, symlinks, and reparse points
    are left untouched. DPAPI and authenticated encryption protect file contents
    at rest; deletion is best-effort and is not secure erasure on SSDs.
    """
    target = Path(directory) if directory is not None else default_spool_directory()
    if not target.exists():
        return []
    if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
        raise SecureSpoolError("Le dossier de spool ne peut pas être un lien ou point de réanalyse.")
    removed: list[Path] = []
    for candidate in target.iterdir():
        match = _SPOOL_NAME.fullmatch(candidate.name)
        if match is None:
            continue
        try:
            st = candidate.lstat()
        except OSError:
            continue
        if candidate.is_symlink() or getattr(st, "st_file_attributes", 0) & 0x400:
            continue
        if not candidate.is_file():
            continue
        pid = int(match.group(1))
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
            continue
        except ProcessLookupError:
            pass
        except PermissionError:
            continue
        except OSError:
            continue
        try:
            candidate.unlink()
            removed.append(candidate)
        except OSError:
            continue
    return removed

