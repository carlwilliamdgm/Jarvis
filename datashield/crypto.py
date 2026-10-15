# datashield/crypto.py
"""Moteur de chiffrement AES-256-GCM pour DataShield (GreatOS).

Ce module fournit :
- Dérivation de clé via PBKDF2-HMAC-SHA256 (argon2id préféré si disponible).
- Chiffrement / déchiffrement AES-256-GCM avec nonce unique par opération.
- Keystore persistent (fichier .key.enc) protégé par une phrase secrète maître.
- API haut niveau utilisée par les stores mémoire et les outils DataShield.

La phrase secrète maître est lue depuis la variable d'environnement
``JARVIS_CRYPTO_KEY``. Sans elle ou sans la bibliothèque cryptography, les
opérations de chiffrement échouent explicitement au lieu de conserver des
données sensibles en clair. Le déchiffrement tolère encore les valeurs legacy.

Algorithmes :
    - AES-256-GCM : confidentialité + intégrité authentifiée.
    - PBKDF2-HMAC-SHA256 (600 000 itérations) : dérivation de clé robuste,
      disponible nativement dans ``cryptography``.
    - Sel aléatoire de 16 octets par dérivation (stocké en tête du blob).

Format du blob chiffré (bytes) :
    [SALT 16B][NONCE 12B][CIPHERTEXT + TAG 16B]

Le tag GCM de 16 octets est intégré par la bibliothèque et extrait automatiquement.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hmac
import logging
import os
import re
import struct
import threading
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

logger = logging.getLogger(__name__)

# ─── Dépendance optionnelle ────────────────────────────────────────────────────

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CRYPTO_AVAILABLE = False
    logger.warning(
        "DataShield/crypto : bibliothèque 'cryptography' non disponible. "
        "Le chiffrement AES-256-GCM est désactivé. "
        "Installez-la avec : pip install 'cryptography>=43.0.0,<45.0.0'"
    )


class _GCMEncryptingWriter:
    """Bounded-memory writer for the byte-compatible DataShield GCM blob format."""

    def __init__(self, destination: BinaryIO, passphrase: bytes, max_input_bytes: int | None):
        self._destination = destination
        self._max_input_bytes = max_input_bytes
        self._input_bytes = 0
        salt = os.urandom(SALT_SIZE)
        nonce = os.urandom(NONCE_SIZE)
        key = _derive_key(passphrase, salt)
        self._encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        _write_all(self._destination, BLOB_HEADER + struct.pack("B", BLOB_VERSION) + salt + nonce)
        self._finalized = False

    def write(self, data: bytes) -> int:
        if self._finalized:
            raise ValueError("Écriture après finalisation du blob DataShield.")
        size = len(data)
        if self._max_input_bytes is not None and self._input_bytes + size > self._max_input_bytes:
            raise ValueError("La taille maximale du snapshot est dépassée.")
        encrypted = self._encryptor.update(data)
        if encrypted:
            _write_all(self._destination, encrypted)
        self._input_bytes += size
        return size

    def tell(self) -> int:
        return self._input_bytes

    def flush(self) -> None:
        self._destination.flush()

    def finalize(self) -> None:
        if self._finalized:
            return
        tail = self._encryptor.finalize()
        if tail:
            _write_all(self._destination, tail)
        _write_all(self._destination, self._encryptor.tag)
        self._destination.flush()
        self._finalized = True


def _write_all(destination: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = destination.write(view)
        if written is None or written <= 0:
            raise OSError("Écriture incomplète du flux DataShield.")
        view = view[written:]

# ─── Constantes ───────────────────────────────────────────────────────────────

SALT_SIZE = 16       # octets
NONCE_SIZE = 12      # octets (96 bits, recommandé pour GCM)
KEY_SIZE = 32        # octets (AES-256)
PBKDF2_ITERATIONS = 600_000
BLOB_HEADER = b"JGCM"    # magic marker — 4 octets
BLOB_VERSION = 1          # versionnement du format (1 octet)
HEADER_SIZE = len(BLOB_HEADER) + 1  # 5 octets
_BLOB_BASE64_PREFIX = base64.b64encode(BLOB_HEADER).decode("ascii")[:4]

_ENV_KEY = "JARVIS_CRYPTO_KEY"


def _plaintext_env_key_allowed(platform_name: str | None = None, environment: str | None = None) -> bool:
    """Permit legacy env keys only outside production on Windows."""
    active_platform = os.name if platform_name is None else platform_name
    active_environment = os.environ.get("GREATOS_ENV", "") if environment is None else environment
    return active_platform != "nt" or active_environment.strip().lower() != "production"


def _decode_encrypted_blob(value: str) -> bytes | None:
    """Décode un blob DataShield, en distinguant les valeurs legacy en clair."""
    try:
        blob = base64.b64decode(value, validate=True)
    except Exception as exc:
        if value.startswith(_BLOB_BASE64_PREFIX):
            raise ValueError("Blob DataShield malformé.") from exc
        return None
    return blob if blob.startswith(BLOB_HEADER) else None


# ─── Utilitaires bas niveau ───────────────────────────────────────────────────

def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
    """Dérive une clé AES-256 depuis une phrase secrète et un sel aléatoire."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Bibliothèque 'cryptography' non installée.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase)


def encrypt_bytes(plaintext: bytes, passphrase: bytes) -> bytes:
    """Chiffre ``plaintext`` avec AES-256-GCM.

    Retourne un blob auto-suffisant incluant le sel, le nonce et le
    ciphertext+tag. Le format est versionnée pour faciliter la migration.

    Args:
        plaintext: Données brutes à chiffrer.
        passphrase: Phrase secrète maître (bytes).

    Returns:
        Blob bytes chiffré.

    Raises:
        RuntimeError: Si la bibliothèque cryptography est absente.
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Chiffrement indisponible : 'cryptography' non installée.")
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    # Format : HEADER | VERSION | SALT | NONCE | CIPHERTEXT
    return BLOB_HEADER + struct.pack("B", BLOB_VERSION) + salt + nonce + ciphertext


def decrypt_bytes(blob: bytes, passphrase: bytes) -> bytes:
    """Déchiffre un blob produit par :func:`encrypt_bytes`.

    Args:
        blob: Blob chiffré.
        passphrase: Phrase secrète maître (bytes).

    Returns:
        Données déchiffrées en clair.

    Raises:
        ValueError: Si le blob est malformé ou le magic header incorrect.
        RuntimeError: Si la bibliothèque cryptography est absente.
        cryptography.exceptions.InvalidTag: Si le tag GCM est invalide
            (données altérées ou mauvaise clé).
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Chiffrement indisponible : 'cryptography' non installée.")
    if len(blob) < HEADER_SIZE + SALT_SIZE + NONCE_SIZE + 16:
        raise ValueError("Blob chiffré trop court ou malformé.")
    if blob[:len(BLOB_HEADER)] != BLOB_HEADER:
        raise ValueError("Magic header DataShield manquant — blob non reconnu.")
    version = struct.unpack("B", blob[len(BLOB_HEADER):HEADER_SIZE])[0]
    if version != BLOB_VERSION:
        raise ValueError(f"Version de blob non supportée : {version}.")
    offset = HEADER_SIZE
    salt = blob[offset:offset + SALT_SIZE]
    offset += SALT_SIZE
    nonce = blob[offset:offset + NONCE_SIZE]
    offset += NONCE_SIZE
    ciphertext = blob[offset:]
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def encrypt_str(plaintext: str, passphrase: bytes) -> str:
    """Chiffre une chaîne et retourne un blob encodé en base64 (safe pour JSON)."""
    blob = encrypt_bytes(plaintext.encode("utf-8"), passphrase)
    return base64.b64encode(blob).decode("ascii")


def decrypt_str(b64_blob: str, passphrase: bytes) -> str:
    """Déchiffre un blob base64 produit par :func:`encrypt_str`."""
    blob = base64.b64decode(b64_blob)
    return decrypt_bytes(blob, passphrase).decode("utf-8")


# ─── CryptoEngine (singleton) ─────────────────────────────────────────────────

class CryptoEngine:
    """Point d'accès centralisé au chiffrement DataShield.

    Lit la phrase secrète maître depuis l'environnement (``JARVIS_CRYPTO_KEY``).
    Si la variable ou la bibliothèque est absente, les opérations de chiffrement
    échouent explicitement; le déchiffrement conserve la lecture legacy en clair.

    Usage::

        from datashield.crypto import crypto_engine

        blob = crypto_engine.encrypt("données sensibles")
        texte = crypto_engine.decrypt(blob)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._passphrase: Optional[bytes] = None
        self._protected_key_path: Optional[Path] = None
        self._hello_envelope_path: Optional[Path] = None
        self._load_passphrase()

    def _load_passphrase(self) -> None:
        self._passphrase = None
        self._protected_key_path = None
        self._hello_envelope_path = None
        try:
            from datashield.env_loader import charger_environnement
            charger_environnement()
        except Exception:
            pass
        if os.name == "nt":
            try:
                from datashield.windows_key_store import key_store_path
                from datashield.prf_key_envelope import envelope_path_for
                protected_path = key_store_path()
                hello_path = envelope_path_for(protected_path)
                if hello_path.is_file():
                    self._hello_envelope_path = hello_path
                    # Startup has no PRF output, so it cannot authenticate the
                    # GCM tag. Keep any DPAPI copy; migration removes it only
                    # after a verified PRF round-trip.
                    from datashield.prf_key_envelope import read_envelope
                    try:
                        read_envelope(hello_path)
                    except Exception:
                        logger.exception("Windows Hello envelope is malformed; retaining any DPAPI recovery copy.")
                if protected_path.is_file():
                    # Validate the CurrentUser DPAPI copy before preferring it.
                    # A Hello envelope remains untouched as a recovery route if
                    # DPAPI is unavailable under this Windows account.
                    from datashield.windows_key_store import unprotect_secret
                    try:
                        unprotect_secret(protected_path)
                    except Exception:
                        if self._hello_envelope_path is None:
                            self._protected_key_path = protected_path
                            return
                    else:
                        self._protected_key_path = protected_path
                        return
                if self._hello_envelope_path is not None:
                    return
                # Do not fall back to a plaintext environment key when a
                # protected store exists but is corrupt or inaccessible.
                if protected_path.exists() or protected_path.is_symlink():
                    self._protected_key_path = protected_path
                    return
            except (ImportError, OSError, RuntimeError):
                logger.exception("Impossible de vérifier le trousseau DataShield Windows.")
            # Production keys must be available only through the Windows
            # protected store. A legacy plaintext key is accepted solely when
            # the operator has not selected production mode (migration/setup
            # can still read the old file and provision DPAPI deliberately).
            if not _plaintext_env_key_allowed("nt"):
                logger.error("DataShield refuse une clé .env en clair en mode production Windows.")
                return
        raw = os.environ.get(_ENV_KEY, "").strip()
        if raw:
            self._passphrase = raw.encode("utf-8")
        else:
            logger.warning(
                "DataShield/crypto : variable d'environnement '%s' non définie. "
                "Le chiffrement des données est désactivé. "
                "Définissez-la pour activer la protection AES-256-GCM.",
                _ENV_KEY,
            )

    @property
    def is_enabled(self) -> bool:
        """Retourne True si le chiffrement est actif (clé + bibliothèque disponibles)."""
        return _CRYPTO_AVAILABLE and self._passphrase is not None

    @property
    def is_locked(self) -> bool:
        """Indique qu'une clé DataShield protégée existe mais n'est pas en mémoire."""
        return ((self._protected_key_path is not None or self.is_hello_wrapped)
                and self._passphrase is None)

    @property
    def is_hello_wrapped(self) -> bool:
        if os.name != "nt":
            return False
        try:
            path = getattr(self, "_hello_envelope_path", None)
            if path is None:
                from datashield.prf_key_envelope import envelope_path_for
                from datashield.windows_key_store import key_store_path
                path = envelope_path_for(key_store_path())
            present = path.exists() or path.is_symlink()
            if not present:
                return False
            # Hello is the active unlock route only while a valid DPAPI copy
            # has not been established. The envelope itself stays as fallback.
            protected = getattr(self, "_protected_key_path", None)
            if protected is None:
                from datashield.windows_key_store import key_store_path, unprotect_secret
                protected = key_store_path()
            if protected.is_file() and not protected.is_symlink():
                from datashield.windows_key_store import unprotect_secret
                unprotect_secret(protected)
                return False
            return True
        except (OSError, RuntimeError, ImportError):
            return True

    @property
    def hello_key_wrapped(self) -> bool:
        """Whether the active Windows key is protected by its Hello PRF envelope."""
        return self.is_hello_wrapped

    @property
    def windows_key_store_mode(self) -> str:
        """Describe the effective Windows key route without exposing key data."""
        if os.name != "nt":
            return "not_applicable"
        if self.is_enabled:
            return "unlocked"
        if self.is_hello_wrapped:
            return "hello_recovery"
        if self.dpapi_recovery_available:
            return "dpapi"
        protected = getattr(self, "_protected_key_path", None)
        if protected is not None:
            return "dpapi_unavailable"
        return "unconfigured"

    def unlock_from_key_store(self) -> None:
        """Charge une clé protégée par Windows DPAPI après authentification de l'appelant."""
        if os.name != "nt":
            raise RuntimeError("Aucune clé DataShield protégée Windows n'est configurée.")
        from datashield.windows_key_store import key_store_path, unprotect_secret
        path = getattr(self, "_protected_key_path", None) or key_store_path()
        secret = unprotect_secret(path)
        self._set_passphrase(secret)

    @property
    def dpapi_recovery_available(self) -> bool:
        """Whether a locked profile can be recovered through its local DPAPI copy."""
        if os.name != "nt" or self.is_enabled:
            return False
        try:
            from datashield.windows_key_store import key_store_path
            path = getattr(self, "_protected_key_path", None) or key_store_path()
            if not path.is_file() or path.is_symlink():
                return False
            from datashield.windows_key_store import unprotect_secret
            unprotect_secret(path)
            return True
        except (OSError, RuntimeError):
            return False

    def unlock_with_manual_key(self, passphrase: str) -> None:
        """Unlock with the recovery key, rebuilding a lost DPAPI copy safely."""
        if os.name == "nt":
            from datashield.windows_key_store import key_store_path, restore_secret_store, verify_recovery_secret
            path = getattr(self, "_protected_key_path", None) or key_store_path()
            if self.is_hello_wrapped:
                if not verify_recovery_secret(passphrase, path):
                    raise ValueError("La clé DataShield fournie ne correspond pas à la clé de secours.")
                if not restore_secret_store(passphrase, path):
                    raise RuntimeError("Impossible de restaurer le coffre DPAPI; l’enveloppe Hello est conservée.")
                from datashield.windows_key_store import unprotect_secret
                if not hmac.compare_digest(unprotect_secret(path), passphrase):
                    raise RuntimeError("La relecture du coffre DPAPI restauré a échoué; l’enveloppe Hello est conservée.")
                self._protected_key_path = path
            elif restore_secret_store(passphrase, path):
                self._protected_key_path = path
            else:
                raise ValueError("La clé DataShield fournie ne correspond pas à la clé de secours.")
        elif self._protected_key_path is not None:
            from datashield.windows_key_store import verify_secret
            if not verify_secret(passphrase, self._protected_key_path):
                raise ValueError("La clé DataShield fournie ne correspond pas à la clé de secours.")
        else:
            expected = os.environ.get(_ENV_KEY, "")
            if not expected or not hmac.compare_digest(passphrase, expected):
                raise ValueError("Aucune clé DataShield configurée ne correspond à la clé fournie.")
        self._set_passphrase(passphrase)

    @staticmethod
    def _decode_prf_output(encoded: str) -> bytes:
        if not isinstance(encoded, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded):
            raise ValueError("Le résultat Windows Hello PRF doit être encodé en base64url sur 32 octets.")
        try:
            value = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
        except Exception as exc:
            raise ValueError("Le résultat Windows Hello PRF est malformé.") from exc
        if len(value) != 32:
            raise ValueError("Le résultat Windows Hello PRF doit contenir exactement 32 octets.")
        return value

    def migrate_to_hello(self, encoded_prf_output: str, prf_salt: bytes) -> None:
        """Reject Hello-only migration while Windows-session DPAPI is the policy."""
        raise RuntimeError("DataShield utilise DPAPI CurrentUser à l’ouverture de session Windows; l’enveloppe Hello ne peut pas remplacer cette protection.")

    def unlock_with_hello_prf(self, encoded_prf_output: str) -> None:
        """Unwrap the DataShield passphrase after a verified PRF assertion."""
        if os.name != "nt":
            raise RuntimeError("Le déverrouillage DataShield Windows est indisponible sur cet OS.")
        if not self.is_hello_wrapped:
            raise RuntimeError("Aucune enveloppe Windows Hello PRF n'est configurée.")
        prf_output = self._decode_prf_output(encoded_prf_output)
        from datashield.prf_key_envelope import envelope_prf_salt, read_envelope, unwrap_secret
        from datashield.windows_key_store import (
            ensure_recovery_check, key_store_path, protect_secret, unprotect_secret,
        )
        envelope = read_envelope(self._hello_envelope_path)
        salt = envelope_prf_salt(envelope)
        secret = unwrap_secret(prf_output, salt, envelope)
        path = key_store_path()
        # Authenticated PRF is the source key for a one-way transition back to
        # the selected Windows-account policy. Keep the Hello envelope intact
        # until DPAPI has been written and read back successfully.
        ensure_recovery_check(secret, path)
        protect_secret(secret, path)
        if not hmac.compare_digest(unprotect_secret(path), secret):
            raise RuntimeError("La validation de la copie DPAPI restaurée a échoué.")
        self._protected_key_path = path
        self._set_passphrase(secret)

    def lock(self) -> None:
        """Retire la clé DataShield de la mémoire active."""
        with self._lock:
            self._passphrase = None

    def reload_passphrase(self) -> None:
        """Recharge la phrase secrète depuis l'environnement (hot-reload)."""
        with self._lock:
            self._load_passphrase()

    def _set_passphrase(self, passphrase: str) -> None:
        """Internal assignment; public unlock entry points verify the key first."""
        with self._lock:
            self._passphrase = passphrase.encode("utf-8") if passphrase else None

    def encrypt(self, plaintext: str) -> str:
        """Chiffre une chaîne.

        Si le chiffrement est désactivé, lève une erreur au lieu de stocker la valeur en clair.

        Args:
            plaintext: Texte en clair.

        Returns:
            Blob base64 chiffré.

        Raises:
            RuntimeError: Si la bibliothèque ou la clé de chiffrement est absente.
        """
        if not self.is_enabled:
            raise RuntimeError("Chiffrement indisponible : bibliothèque ou clé DataShield absente.")
        with self._lock:
            return encrypt_str(plaintext, self._passphrase)  # type: ignore[arg-type]

    def decrypt(self, value: str, strict: bool = False) -> str:
        """Déchiffre une valeur produite par :meth:`encrypt`.

        Si le chiffrement est désactivé ou si la valeur n'est pas un blob
        DataShield reconnu, retourne la valeur inchangée (compatibilité lectures
        non chiffrées existantes).

        Args:
            value: Blob base64 ou valeur en clair.

        Returns:
            Texte déchiffré ou ``value`` original si non applicable.
        """
        try:
            blob = _decode_encrypted_blob(value)
        except ValueError:
            if strict:
                raise
            return value
        if blob is None:
            return value
        if not self.is_enabled:
            if strict:
                raise RuntimeError("Impossible de déchiffrer : bibliothèque ou clé DataShield absente.")
            return value
        try:
            with self._lock:
                return decrypt_bytes(blob, self._passphrase).decode("utf-8")  # type: ignore[arg-type]
        except Exception:
            if strict:
                raise
            # Valeur non chiffrée ou format inconnu — retour transparent
            return value

    def encrypt_bytes(self, data: bytes) -> bytes:
        """Chiffre des bytes bruts; échoue si DataShield n'est pas prêt."""
        if not self.is_enabled:
            raise RuntimeError("Chiffrement indisponible : bibliothèque ou clé DataShield absente.")
        with self._lock:
            return encrypt_bytes(data, self._passphrase)  # type: ignore[arg-type]

    def decrypt_bytes(self, data: bytes, strict: bool = False) -> bytes:
        """Déchiffre des bytes. Retourne les bytes inchangés si non-blob DataShield.

        Si strict=True et que data est un blob chiffré dont le déchiffrement échoue,
        l'exception sous-jacente est levée au lieu de renvoyer le ciphertext brut.
        """
        if not self.is_enabled:
            if strict and data[:len(BLOB_HEADER)] == BLOB_HEADER:
                raise RuntimeError("Chiffrement DataShield inactif (JARVIS_CRYPTO_KEY non définie).")
            return data
        if data[:len(BLOB_HEADER)] != BLOB_HEADER:
            return data
        try:
            with self._lock:
                return decrypt_bytes(data, self._passphrase)  # type: ignore[arg-type]
        except Exception:
            if strict:
                raise
            return data

    @contextmanager
    def encrypting_writer(
        self,
        destination: BinaryIO,
        max_input_bytes: int | None = None,
    ) -> Iterator[_GCMEncryptingWriter]:
        """Yield a streaming AES-GCM writer using the existing DataShield blob format.

        The destination must be a disposable temporary file: if the caller exits
        with an exception, the ciphertext is intentionally left unfinalized and
        must not be published.
        """
        if not self.is_enabled:
            raise RuntimeError("Chiffrement indisponible : bibliothèque ou clé DataShield absente.")
        with self._lock:
            writer = _GCMEncryptingWriter(destination, self._passphrase, max_input_bytes)  # type: ignore[arg-type]
            try:
                yield writer
                writer.finalize()
            except BaseException:
                raise

    def decrypt_stream(
        self,
        source: BinaryIO,
        destination: BinaryIO,
        *,
        max_input_bytes: int,
        max_output_bytes: int,
        chunk_size: int = 1024 * 1024,
    ) -> int:
        """Authenticate/decrypt a DataShield blob with bounded memory.

        Plaintext can be written to ``destination`` before GCM verifies its tag;
        callers must supply a private temporary output and discard it on errors.
        """
        if not self.is_enabled:
            raise RuntimeError("Déchiffrement indisponible : DataShield est verrouillé.")
        if chunk_size <= 0 or max_input_bytes < HEADER_SIZE + SALT_SIZE + NONCE_SIZE + 16:
            raise ValueError("Limites de déchiffrement invalides.")
        with self._lock:
            start = destination.tell() if destination.seekable() else None
            try:
                header = source.read(HEADER_SIZE + SALT_SIZE + NONCE_SIZE)
                if len(header) != HEADER_SIZE + SALT_SIZE + NONCE_SIZE:
                    raise ValueError("Blob DataShield tronqué.")
                if header[:len(BLOB_HEADER)] != BLOB_HEADER:
                    raise ValueError("Magic header DataShield manquant — blob non reconnu.")
                version = struct.unpack("B", header[len(BLOB_HEADER):HEADER_SIZE])[0]
                if version != BLOB_VERSION:
                    raise ValueError(f"Version de blob non supportée : {version}.")
                salt_offset = HEADER_SIZE
                salt = header[salt_offset:salt_offset + SALT_SIZE]
                nonce_offset = salt_offset + SALT_SIZE
                nonce = header[nonce_offset:nonce_offset + NONCE_SIZE]
                decryptor = Cipher(
                    algorithms.AES(_derive_key(self._passphrase, salt)),  # type: ignore[arg-type]
                    modes.GCM(nonce),
                ).decryptor()

                total_input = len(header)
                total_output = 0
                pending = b""
                while True:
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    total_input += len(chunk)
                    if total_input > max_input_bytes:
                        raise ValueError("La taille chiffrée maximale du snapshot est dépassée.")
                    pending += chunk
                    if len(pending) > 16:
                        body, pending = pending[:-16], pending[-16:]
                        plaintext = decryptor.update(body)
                        total_output += len(plaintext)
                        if total_output > max_output_bytes:
                            raise ValueError("La taille décompressée maximale du snapshot est dépassée.")
                        _write_all(destination, plaintext)
                if total_input < HEADER_SIZE + SALT_SIZE + NONCE_SIZE + 16 or len(pending) != 16:
                    raise ValueError("Blob DataShield tronqué ou sans tag GCM.")
                tail = decryptor.finalize_with_tag(pending)
                total_output += len(tail)
                if total_output > max_output_bytes:
                    raise ValueError("La taille décompressée maximale du snapshot est dépassée.")
                if tail:
                    _write_all(destination, tail)
                destination.flush()
                return total_output
            except BaseException:
                if start is not None:
                    try:
                        destination.seek(start)
                        destination.truncate()
                    except OSError:
                        pass
                raise

    def status(self) -> dict:
        """Retourne l'état du moteur de chiffrement (sans exposer la clé)."""
        return {
            "enabled": self.is_enabled,
            "library_available": _CRYPTO_AVAILABLE,
            "key_configured": self._passphrase is not None,
            "algorithm": "AES-256-GCM",
            "kdf": "PBKDF2-HMAC-SHA256",
            "kdf_iterations": PBKDF2_ITERATIONS,
            "key_size_bits": KEY_SIZE * 8,
            "hello_prf_wrapped": self.is_hello_wrapped,
            "windows_key_store_mode": self.windows_key_store_mode,
        }


# Singleton d'application
crypto_engine = CryptoEngine()
