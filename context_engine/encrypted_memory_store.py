# context_engine/encrypted_memory_store.py
"""Store mémoire avec chiffrement transparent AES-256-GCM.

Ce module fournit ``EncryptedJsonMemoryStore``, une couche de chiffrement
transparent au-dessus de ``JsonMemoryStore``.

Les valeurs sensibles (champs listés dans ``SENSITIVE_KEYS`` ou dont la clé
contient ``secret``, ``token``, ``password``, ``key``, ``api``) sont chiffrées
individuellement avant écriture sur disque. Les clés restent en clair pour
permettre la navigation de la structure sans déchiffrement complet.

Stratégie de migration :
    - Si une valeur sur disque n'est pas un blob DataShield reconnu, elle est
      lue telle quelle et éventuellement rechiffrée à la prochaine sauvegarde.
    - Cette stratégie garantit une migration transparente depuis un store non
      chiffré existant.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from context_engine.memory_store import BaseMemoryStore, JsonMemoryStore, _GLOBAL_MEMORY_LOCK
from datashield.crypto import crypto_engine

logger = logging.getLogger(__name__)

# Clés considérées comme sensibles — chiffrées individuellement.
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "notes",
    "preferences",
    "historique_conversation",
    "journal_actions",
    "taches",
    "contexte_personnel",
    "profil",
})

# Fragments dans une clé qui indiquent qu'elle est sensible.
_SENSITIVE_FRAGMENTS: tuple[str, ...] = (
    "secret", "token", "password", "key", "api", "credential",
)


def _is_sensitive_key(key: str) -> bool:
    """Retourne True si la clé doit être chiffrée."""
    if key in SENSITIVE_KEYS:
        return True
    key_lower = key.lower()
    return any(frag in key_lower for frag in _SENSITIVE_FRAGMENTS)


class EncryptedJsonMemoryStore(BaseMemoryStore):
    """Store JSON avec chiffrement sélectif des valeurs sensibles.

    Délègue la persistence à un ``JsonMemoryStore`` sous-jacent et applique
    le chiffrement/déchiffrement à la volée sur les champs identifiés comme
    sensibles.

    Si le ``CryptoEngine`` est désactivé (clé absente ou bibliothèque manquante),
    ce store se comporte exactement comme un ``JsonMemoryStore`` classique —
    aucune perte de données, aucune erreur silencieuse.
    """

    def __init__(self, file_path: Optional[Path] = None) -> None:
        self._inner = JsonMemoryStore(file_path)
        if not crypto_engine.is_enabled:
            logger.warning(
                "EncryptedJsonMemoryStore : chiffrement désactivé (CryptoEngine inactif). "
                "Les données seront stockées en clair."
            )

    def _encrypt_sensitive(self, data: dict) -> dict:
        """Retourne un dict avec les valeurs sensibles chiffrées."""
        if not crypto_engine.is_enabled:
            return data
        encrypted = {}
        for key, value in data.items():
            if _is_sensitive_key(key):
                try:
                    serialized = json.dumps(value, ensure_ascii=False)
                    encrypted[key] = crypto_engine.encrypt(serialized)
                except Exception as exc:
                    logger.error("Échec chiffrement clé '%s': %s", key, exc)
                    encrypted[key] = value  # Fallback : valeur non chiffrée
            else:
                encrypted[key] = value
        return encrypted

    def _decrypt_sensitive(self, data: dict) -> dict:
        """Retourne un dict avec les valeurs sensibles déchiffrées."""
        if not crypto_engine.is_enabled:
            return data
        decrypted = {}
        for key, value in data.items():
            if _is_sensitive_key(key) and isinstance(value, str):
                try:
                    decrypted_str = crypto_engine.decrypt(value)
                    # Si la valeur a été chiffrée, c'était du JSON sérialisé
                    if decrypted_str != value:
                        decrypted[key] = json.loads(decrypted_str)
                    else:
                        decrypted[key] = value  # Valeur non chiffrée (migration)
                except Exception as exc:
                    logger.error("Échec déchiffrement clé '%s': %s", key, exc)
                    decrypted[key] = value  # Fallback : valeur brute
            else:
                decrypted[key] = value
        return decrypted

    def load(self) -> dict:
        """Charge et déchiffre les données depuis le store sous-jacent."""
        raw = self._inner.load()
        return self._decrypt_sensitive(raw)

    def save(self, data: dict) -> None:
        """Chiffre les données sensibles et les persiste."""
        encrypted = self._encrypt_sensitive(data)
        self._inner.save(encrypted)

    @contextmanager
    def transaction(self) -> Generator[dict, None, None]:
        """Transaction ACID avec chiffrement transparent."""
        from context_engine.memory import normaliser_memoire
        with _GLOBAL_MEMORY_LOCK:
            data = normaliser_memoire(self.load())
            yield data
            self.save(data)

    def close(self) -> None:
        self._inner.close()
