# context_engine/encrypted_memory_store.py
"""Persistance mémoire JSON chiffrée avec AES-256-GCM.

Le backend chiffre le document mémoire complet avant de le confier au store
JSON atomique. Les anciennes mémoires JSON en clair sont migrées à la création
du backend; une erreur de chiffrement ou d'intégrité bloque explicitement la
lecture ou l'écriture au lieu de revenir au clair.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Generator

from context_engine.memory_store import BaseMemoryStore, JsonMemoryStore, _GLOBAL_MEMORY_LOCK
from datashield.crypto import crypto_engine

_ENVELOPE_KEY = "__greatos_encrypted_memory_v1__"
_LEGACY_ENCRYPTED_KEYS = frozenset({
    "notes", "preferences", "historique_conversation", "journal_actions",
    "taches", "contexte_personnel", "profil",
})


class EncryptedJsonMemoryStore(BaseMemoryStore):
    """Store JSON dont toutes les données mémoire sont protégées au repos."""

    def __init__(self, file_path=None) -> None:
        if not crypto_engine.is_enabled:
            raise RuntimeError(
                "Backend mémoire chiffré indisponible : configurez la bibliothèque "
                "cryptography et JARVIS_CRYPTO_KEY."
            )
        self._inner = JsonMemoryStore(file_path)
        # La sélection du backend chiffré ne doit pas laisser en clair une
        # mémoire existante en attendant une prochaine modification utilisateur.
        with _GLOBAL_MEMORY_LOCK:
            raw = self._inner.load()
            if _ENVELOPE_KEY in raw:
                self._decode_envelope(raw)
            elif raw:
                self.save(self._decode_legacy_selective_fields(raw))

    @staticmethod
    def _decode_legacy_selective_fields(raw: dict) -> dict:
        """Reconstruit l'ancien format où seuls certains champs étaient chiffrés."""
        data = dict(raw)
        for key, value in raw.items():
            key_lower = str(key).lower()
            sensitive = key in _LEGACY_ENCRYPTED_KEYS or any(
                fragment in key_lower
                for fragment in ("secret", "token", "password", "key", "api", "credential")
            )
            if not sensitive or not isinstance(value, str):
                continue
            try:
                plaintext = crypto_engine.decrypt(value, strict=True)
                if plaintext != value:
                    data[key] = json.loads(plaintext)
            except Exception as exc:
                raise RuntimeError(
                    f"Migration mémoire refusée : impossible de déchiffrer le champ '{key}'."
                ) from exc
        return data

    def _decode_envelope(self, raw: dict) -> dict:
        if set(raw) != {_ENVELOPE_KEY} or not isinstance(raw.get(_ENVELOPE_KEY), str):
            raise RuntimeError("Enveloppe de mémoire chiffrée invalide; lecture refusée.")
        try:
            plaintext = crypto_engine.decrypt(raw[_ENVELOPE_KEY], strict=True)
            data = json.loads(plaintext)
        except Exception as exc:
            raise RuntimeError("Mémoire chiffrée illisible; lecture refusée.") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Document mémoire chiffré invalide; lecture refusée.")
        return data

    def load(self) -> dict:
        """Charge le document complet depuis son enveloppe chiffrée."""
        raw = self._inner.load()
        if not raw:
            return {}
        if _ENVELOPE_KEY not in raw:
            # Compatibilité pendant une migration explicite/incomplète.
            return raw
        return self._decode_envelope(raw)

    def save(self, data: dict) -> None:
        """Chiffre le document complet; aucune erreur ne retombe en clair."""
        if not isinstance(data, dict):
            raise TypeError("La mémoire à persister doit être un dictionnaire.")
        if not crypto_engine.is_enabled:
            raise RuntimeError("Écriture refusée : le chiffrement DataShield est requis.")
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        ciphertext = crypto_engine.encrypt(serialized)
        self._inner.save({_ENVELOPE_KEY: ciphertext})

    @contextmanager
    def transaction(self) -> Generator[dict, None, None]:
        """Transaction atomique avec chiffrement avant écriture disque."""
        from context_engine.memory import normaliser_memoire
        with _GLOBAL_MEMORY_LOCK:
            data = normaliser_memoire(self.load())
            yield data
            self.save(data)

    def close(self) -> None:
        self._inner.close()
