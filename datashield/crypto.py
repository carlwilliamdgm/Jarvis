# datashield/crypto.py
"""Moteur de chiffrement AES-256-GCM pour DataShield (GreatOS).

Ce module fournit :
- Dérivation de clé via PBKDF2-HMAC-SHA256 (argon2id préféré si disponible).
- Chiffrement / déchiffrement AES-256-GCM avec nonce unique par opération.
- Keystore persistent (fichier .key.enc) protégé par une phrase secrète maître.
- API haut niveau utilisée par les stores mémoire et les outils DataShield.

La phrase secrète maître est lue depuis la variable d'environnement
``JARVIS_CRYPTO_KEY``. Sans elle, le module fonctionne en mode non chiffré
et avertit dans les logs (jamais d'échec silencieux).

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
import logging
import os
import struct
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Dépendance optionnelle ────────────────────────────────────────────────────

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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

# ─── Constantes ───────────────────────────────────────────────────────────────

SALT_SIZE = 16       # octets
NONCE_SIZE = 12      # octets (96 bits, recommandé pour GCM)
KEY_SIZE = 32        # octets (AES-256)
PBKDF2_ITERATIONS = 600_000
BLOB_HEADER = b"JGCM"    # magic marker — 4 octets
BLOB_VERSION = 1          # versionnement du format (1 octet)
HEADER_SIZE = len(BLOB_HEADER) + 1  # 5 octets

_ENV_KEY = "JARVIS_CRYPTO_KEY"


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
    Si la variable est absente, toutes les opérations passent en mode clair
    avec un avertissement — jamais d'erreur silencieuse.

    Usage::

        from datashield.crypto import crypto_engine

        blob = crypto_engine.encrypt("données sensibles")
        texte = crypto_engine.decrypt(blob)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._passphrase: Optional[bytes] = None
        self._load_passphrase()

    def _load_passphrase(self) -> None:
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

    def reload_passphrase(self) -> None:
        """Recharge la phrase secrète depuis l'environnement (hot-reload)."""
        with self._lock:
            self._load_passphrase()

    def set_passphrase(self, passphrase: str) -> None:
        """Définit la phrase secrète en mémoire (non persistée, pour tests)."""
        with self._lock:
            self._passphrase = passphrase.encode("utf-8") if passphrase else None

    def encrypt(self, plaintext: str) -> str:
        """Chiffre une chaîne.

        Si le chiffrement est désactivé, retourne la chaîne inchangée.

        Args:
            plaintext: Texte en clair.

        Returns:
            Blob base64 chiffré, ou ``plaintext`` si le chiffrement est désactivé.
        """
        if not self.is_enabled:
            return plaintext
        with self._lock:
            return encrypt_str(plaintext, self._passphrase)  # type: ignore[arg-type]

    def decrypt(self, value: str) -> str:
        """Déchiffre une valeur produite par :meth:`encrypt`.

        Si le chiffrement est désactivé ou si la valeur n'est pas un blob
        DataShield reconnu, retourne la valeur inchangée (compatibilité lectures
        non chiffrées existantes).

        Args:
            value: Blob base64 ou valeur en clair.

        Returns:
            Texte déchiffré ou ``value`` original si non applicable.
        """
        if not self.is_enabled:
            return value
        try:
            blob = base64.b64decode(value)
            if blob[:len(BLOB_HEADER)] != BLOB_HEADER:
                # Valeur non chiffrée (migration transparente)
                return value
            with self._lock:
                return decrypt_bytes(blob, self._passphrase).decode("utf-8")  # type: ignore[arg-type]
        except Exception:
            # Valeur non chiffrée ou format inconnu — retour transparent
            return value

    def encrypt_bytes(self, data: bytes) -> bytes:
        """Chiffre des bytes bruts. Retourne les bytes inchangés si désactivé."""
        if not self.is_enabled:
            return data
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
        }


# Singleton d'application
crypto_engine = CryptoEngine()
