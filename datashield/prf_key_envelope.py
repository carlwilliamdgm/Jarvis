"""Versioned AES-GCM envelope for a DataShield master passphrase.

This module is deliberately not wired into the application key path. It keeps
the cryptographic format and persistence primitives independently testable.
The PRF result must come from a separately verified WebAuthn assertion, and
callers must never log or serialize it.
"""

from __future__ import annotations

import hmac
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"GOSPRFKE"
VERSION = 1
PRF_OUTPUT_SIZE = 32
PRF_SALT_SIZE = 32
HKDF_SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32
TAG_SIZE = 16
MAX_PASSPHRASE_SIZE = 64 * 1024
_HEADER_SIZE = len(MAGIC) + 1 + PRF_SALT_SIZE + HKDF_SALT_SIZE
_MIN_ENVELOPE_SIZE = _HEADER_SIZE + NONCE_SIZE + TAG_SIZE
_MAX_ENVELOPE_SIZE = _HEADER_SIZE + NONCE_SIZE + MAX_PASSPHRASE_SIZE + TAG_SIZE
_HKDF_INFO = b"GreatOS DataShield PRF master-key wrapping v1"


class PrfEnvelopeError(ValueError):
    """Malformed input, failed authentication, or failed recovery validation."""


def _passphrase_bytes(passphrase: str) -> bytes:
    if not isinstance(passphrase, str) or not passphrase:
        raise PrfEnvelopeError("La clé DataShield doit être une chaîne non vide.")
    try:
        value = passphrase.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise PrfEnvelopeError("La clé DataShield n'est pas un UTF-8 valide.") from exc
    if len(value) > MAX_PASSPHRASE_SIZE or b"\x00" in value:
        raise PrfEnvelopeError("La clé DataShield dépasse la limite ou contient un octet nul.")
    return value


def _prf_output(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != PRF_OUTPUT_SIZE:
        raise PrfEnvelopeError("Le résultat PRF doit contenir exactement 32 octets.")
    return value


def _derive_kek(prf_output: bytes, salt: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        info=_HKDF_INFO,
    ).derive(_prf_output(prf_output))


def create_envelope(
    master_passphrase: str,
    prf_output: bytes,
    *,
    prf_salt: bytes | None = None,
    hkdf_salt: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    """Encrypt the existing passphrase; salts are persisted as public metadata.

    ``prf_salt`` is the stable WebAuthn PRF input associated with the credential.
    It is included so the caller can request the same PRF result after restart.
    Optional entropy parameters exist for deterministic format tests only.
    """
    plaintext = _passphrase_bytes(master_passphrase)
    prf = _prf_output(prf_output)
    input_salt = os.urandom(PRF_SALT_SIZE) if prf_salt is None else prf_salt
    kdf_salt = os.urandom(HKDF_SALT_SIZE) if hkdf_salt is None else hkdf_salt
    iv = os.urandom(NONCE_SIZE) if nonce is None else nonce
    if not isinstance(input_salt, bytes) or len(input_salt) != PRF_SALT_SIZE:
        raise PrfEnvelopeError("Le salt PRF doit contenir exactement 32 octets.")
    if not isinstance(kdf_salt, bytes) or len(kdf_salt) != HKDF_SALT_SIZE:
        raise PrfEnvelopeError("Le salt HKDF doit contenir exactement 16 octets.")
    if not isinstance(iv, bytes) or len(iv) != NONCE_SIZE:
        raise PrfEnvelopeError("Le nonce AES-GCM doit contenir exactement 12 octets.")

    header = MAGIC + bytes([VERSION]) + input_salt + kdf_salt
    ciphertext = AESGCM(_derive_kek(prf, kdf_salt)).encrypt(iv, plaintext, header)
    return header + iv + ciphertext


def wrap_secret(prf_result: bytes, salt: bytes, secret: str) -> bytes:
    """Wrap ``secret`` using the supplied stable WebAuthn PRF input salt."""
    return create_envelope(secret, prf_result, prf_salt=salt)


def envelope_prf_salt(envelope: bytes) -> bytes:
    """Return the public stable WebAuthn PRF input after structural validation."""
    if (not isinstance(envelope, bytes) or len(envelope) < _MIN_ENVELOPE_SIZE
            or len(envelope) > _MAX_ENVELOPE_SIZE):
        raise PrfEnvelopeError("Enveloppe PRF absente, trop courte ou malformée.")
    if envelope[:len(MAGIC)] != MAGIC:
        raise PrfEnvelopeError("Signature d'enveloppe PRF invalide.")
    if envelope[len(MAGIC)] != VERSION:
        raise PrfEnvelopeError("Version d'enveloppe PRF non prise en charge.")
    start = len(MAGIC) + 1
    return envelope[start:start + PRF_SALT_SIZE]


def unwrap_envelope(envelope: bytes, prf_output: bytes) -> str:
    """Authenticate and decrypt a version 1 DataShield passphrase envelope."""
    _prf_output(prf_output)
    if (not isinstance(envelope, bytes) or len(envelope) < _MIN_ENVELOPE_SIZE
            or len(envelope) > _MAX_ENVELOPE_SIZE):
        raise PrfEnvelopeError("Enveloppe PRF absente, trop courte ou malformée.")
    if envelope[:len(MAGIC)] != MAGIC:
        raise PrfEnvelopeError("Signature d'enveloppe PRF invalide.")
    if envelope[len(MAGIC)] != VERSION:
        raise PrfEnvelopeError("Version d'enveloppe PRF non prise en charge.")

    header = envelope[:_HEADER_SIZE]
    offset = len(MAGIC) + 1
    input_salt = envelope[offset:offset + PRF_SALT_SIZE]
    offset += PRF_SALT_SIZE
    kdf_salt = envelope[offset:offset + HKDF_SALT_SIZE]
    offset += HKDF_SALT_SIZE
    nonce = envelope[offset:offset + NONCE_SIZE]
    offset += NONCE_SIZE
    try:
        plaintext = AESGCM(_derive_kek(prf_output, kdf_salt)).decrypt(
            nonce, envelope[offset:], header
        )
        decoded = plaintext.decode("utf-8", errors="strict")
    except Exception as exc:
        raise PrfEnvelopeError("Échec d'authentification de l'enveloppe PRF.") from exc
    _passphrase_bytes(decoded)
    if len(input_salt) != PRF_SALT_SIZE:  # defensive invariant for future format revisions
        raise PrfEnvelopeError("Salt PRF malformé.")
    return decoded


def unwrap_secret(prf_result: bytes, salt: bytes, envelope: bytes) -> str:
    """Unwrap only when the caller's stable WebAuthn salt matches the envelope."""
    if not isinstance(salt, bytes) or len(salt) != PRF_SALT_SIZE:
        raise PrfEnvelopeError("Le salt PRF doit contenir exactement 32 octets.")
    if not hmac.compare_digest(envelope_prf_salt(envelope), salt):
        raise PrfEnvelopeError("Le salt PRF ne correspond pas à cette enveloppe.")
    return unwrap_envelope(envelope, prf_result)


def envelope_path_for(key_store_path: Path) -> Path:
    """Return the stable Hello envelope path adjacent to the legacy key store."""
    path = Path(key_store_path)
    if not path.is_absolute():
        raise PrfEnvelopeError("Le chemin du key store doit être absolu.")
    return path.with_name("hello-key.wrap")


def read_envelope(path: Path) -> bytes:
    """Read a bounded envelope without following a symbolic link."""
    source = Path(path)
    if not source.is_absolute():
        raise PrfEnvelopeError("Le chemin de l'enveloppe doit être absolu.")
    try:
        if source.is_symlink():
            raise PrfEnvelopeError("L'enveloppe ne peut pas être un lien symbolique.")
        if source.stat().st_size > _MAX_ENVELOPE_SIZE:
            raise PrfEnvelopeError("L'enveloppe dépasse la taille maximale autorisée.")
        payload = source.read_bytes()
    except PrfEnvelopeError:
        raise
    except OSError as exc:
        raise PrfEnvelopeError("Impossible de lire l'enveloppe PRF.") from exc
    envelope_prf_salt(payload)
    return payload


def create_recovery_validated_envelope(
    master_passphrase: str,
    prf_output: bytes,
    recovery_store_path: Path,
) -> bytes:
    """Create an envelope only if master-key.check accepts the manual key."""
    from datashield.windows_key_store import verify_recovery_secret

    if not verify_recovery_secret(master_passphrase, recovery_store_path):
        raise PrfEnvelopeError("La clé fournie ne correspond pas au vérificateur de secours.")
    return create_envelope(master_passphrase, prf_output)


def write_envelope_atomic(
    destination: Path,
    envelope: bytes,
    master_passphrase: str,
    prf_output: bytes,
    recovery_store_path: Path,
) -> Path:
    """Persist a new envelope without replacing an existing file.

    The recovery verifier and ciphertext are checked before publication. The
    temporary file is created alongside the destination, fsynced, read back,
    and only then linked atomically into the final name. Existing files fail
    closed, so this primitive cannot silently replace an enrolled key envelope.
    """
    from datashield.windows_key_store import verify_recovery_secret

    target = Path(destination)
    if not target.is_absolute():
        raise PrfEnvelopeError("Le chemin de l'enveloppe doit être absolu.")
    _passphrase_bytes(master_passphrase)
    _prf_output(prf_output)
    if not verify_recovery_secret(master_passphrase, recovery_store_path):
        raise PrfEnvelopeError("La clé fournie ne correspond pas au vérificateur de secours.")
    if not hmac.compare_digest(unwrap_envelope(envelope, prf_output), master_passphrase):
        raise PrfEnvelopeError("L'enveloppe ne contient pas la clé DataShield attendue.")

    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(envelope)
            stream.flush()
            os.fsync(stream.fileno())
        persisted = temporary.read_bytes()
        if not hmac.compare_digest(unwrap_envelope(persisted, prf_output), master_passphrase):
            raise PrfEnvelopeError("La vérification de lecture de l'enveloppe a échoué.")
        # Same-volume rename is atomic and refuses replacement on Windows.
        if os.name == "nt":
            os.rename(temporary, target)
            temporary = None
        else:
            # POSIX rename replaces an existing file; hard-link publication does not.
            os.link(temporary, target)
            temporary.unlink()
            temporary = None
        return target
    except FileExistsError as exc:
        raise PrfEnvelopeError("Une enveloppe existe déjà; remplacement refusé.") from exc
    except PrfEnvelopeError:
        raise
    except OSError as exc:
        raise PrfEnvelopeError("Impossible d'écrire atomiquement l'enveloppe PRF.") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
