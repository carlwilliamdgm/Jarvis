# tests/test_datashield_crypto.py
"""Tests unitaires pour le moteur de chiffrement AES-256-GCM de DataShield.

Couvre :
- Chiffrement / déchiffrement round-trip (bytes et str).
- Format du blob (magic header, version).
- Comportement dégradé sans clé (CryptoEngine désactivé).
- Chiffrement sélectif dans EncryptedJsonMemoryStore.
- Migration transparente depuis un store non chiffré.
- Outils publics (statut_chiffrement, chiffrer_valeur, dechiffrer_valeur).
- Détection d'altération (tag GCM invalide).
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Imports sous test ────────────────────────────────────────────────────────

from datashield.crypto import (
    BLOB_HEADER,
    CryptoEngine,
    decrypt_bytes,
    decrypt_str,
    encrypt_bytes,
    encrypt_str,
    crypto_engine,
)
from datashield.tools import (
    chiffrer_valeur,
    dechiffrer_valeur,
    statut_chiffrement,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

PASSPHRASE = b"test-passphrase-securisee-2026"


@pytest.fixture()
def engine_with_key():
    """CryptoEngine avec une clé de test (isolé du singleton global)."""
    engine = CryptoEngine.__new__(CryptoEngine)
    engine._passphrase = PASSPHRASE
    import threading
    engine._lock = threading.Lock()
    return engine


@pytest.fixture()
def engine_no_key():
    """CryptoEngine sans clé (chiffrement désactivé)."""
    engine = CryptoEngine.__new__(CryptoEngine)
    engine._passphrase = None
    import threading
    engine._lock = threading.Lock()
    return engine


# ─── Tests bas niveau (encrypt/decrypt functions) ─────────────────────────────

class TestEncryptDecryptBytes:
    def test_round_trip(self):
        data = b"donnees sensibles"
        blob = encrypt_bytes(data, PASSPHRASE)
        assert decrypt_bytes(blob, PASSPHRASE) == data

    def test_blob_starts_with_magic_header(self):
        blob = encrypt_bytes(b"test", PASSPHRASE)
        assert blob[:len(BLOB_HEADER)] == BLOB_HEADER

    def test_different_nonce_each_call(self):
        """Deux chiffrements du même texte produisent des blobs différents."""
        data = b"meme texte"
        blob1 = encrypt_bytes(data, PASSPHRASE)
        blob2 = encrypt_bytes(data, PASSPHRASE)
        assert blob1 != blob2

    def test_wrong_passphrase_raises(self):
        from cryptography.exceptions import InvalidTag
        blob = encrypt_bytes(b"secret", PASSPHRASE)
        with pytest.raises(InvalidTag):
            decrypt_bytes(blob, b"mauvaise-cle")

    def test_truncated_blob_raises_value_error(self):
        with pytest.raises(ValueError, match="trop court"):
            decrypt_bytes(b"court", PASSPHRASE)

    def test_wrong_magic_header_raises_value_error(self):
        blob = encrypt_bytes(b"test", PASSPHRASE)
        tampered = b"XXXX" + blob[4:]
        with pytest.raises(ValueError, match="Magic header"):
            decrypt_bytes(tampered, PASSPHRASE)

    def test_altered_ciphertext_raises_invalid_tag(self):
        from cryptography.exceptions import InvalidTag
        blob = bytearray(encrypt_bytes(b"original", PASSPHRASE))
        blob[-1] ^= 0xFF  # Altération du dernier octet (tag GCM)
        with pytest.raises(InvalidTag):
            decrypt_bytes(bytes(blob), PASSPHRASE)


class TestEncryptDecryptStr:
    def test_round_trip(self):
        text = "Données utilisateur confidentielles 🔒"
        blob = encrypt_str(text, PASSPHRASE)
        assert decrypt_str(blob, PASSPHRASE) == text

    def test_output_is_base64(self):
        blob = encrypt_str("test", PASSPHRASE)
        # Doit être décodable sans exception
        decoded = base64.b64decode(blob)
        assert decoded[:len(BLOB_HEADER)] == BLOB_HEADER


# ─── Tests CryptoEngine ───────────────────────────────────────────────────────

class TestCryptoEngine:
    def test_encrypt_decrypt_round_trip(self, engine_with_key):
        original = "données sensibles de Carl"
        encrypted = engine_with_key.encrypt(original)
        assert encrypted != original
        assert engine_with_key.decrypt(encrypted) == original

    def test_encrypt_returns_plaintext_when_disabled(self, engine_no_key):
        text = "en clair"
        assert engine_no_key.encrypt(text) == text

    def test_decrypt_returns_value_unchanged_when_disabled(self, engine_no_key):
        text = "valeur quelconque"
        assert engine_no_key.decrypt(text) == text

    def test_decrypt_non_blob_returns_unchanged(self, engine_with_key):
        """Une valeur non chiffrée (migration) est retournée telle quelle."""
        plain = "valeur legacy non chiffrée"
        assert engine_with_key.decrypt(plain) == plain

    def test_is_enabled_with_key(self, engine_with_key):
        assert engine_with_key.is_enabled is True

    def test_is_enabled_without_key(self, engine_no_key):
        assert engine_no_key.is_enabled is False

    def test_status_dict(self, engine_with_key):
        status = engine_with_key.status()
        assert status["enabled"] is True
        assert status["algorithm"] == "AES-256-GCM"
        assert status["key_size_bits"] == 256
        assert "passphrase" not in str(status)  # Aucune clé exposée

    def test_set_passphrase(self):
        engine = CryptoEngine.__new__(CryptoEngine)
        import threading
        engine._lock = threading.Lock()
        engine._passphrase = None
        assert engine.is_enabled is False
        engine.set_passphrase("nouvelle-cle")
        assert engine.is_enabled is True

    def test_encrypt_bytes_round_trip(self, engine_with_key):
        data = b"\x00\xFF\xAA\x42"
        encrypted = engine_with_key.encrypt_bytes(data)
        assert encrypted != data
        assert engine_with_key.decrypt_bytes(encrypted) == data


# ─── Tests EncryptedJsonMemoryStore ──────────────────────────────────────────

class TestEncryptedJsonMemoryStore:
    def _make_store(self, tmp_path: Path, engine: CryptoEngine):
        """Crée un store avec engine injecté."""
        from context_engine.encrypted_memory_store import EncryptedJsonMemoryStore
        store = EncryptedJsonMemoryStore(tmp_path / "memory.json")
        store._inner.file_path = tmp_path / "memory.json"
        # Injection du moteur de chiffrement via patch
        import datashield.crypto as crypto_mod
        return store, crypto_mod

    def test_sensitive_key_is_encrypted_on_disk(self, tmp_path, engine_with_key):
        """Une clé sensible doit être chiffrée dans le fichier JSON."""
        from context_engine.encrypted_memory_store import EncryptedJsonMemoryStore
        with patch("context_engine.encrypted_memory_store.crypto_engine", engine_with_key):
            store = EncryptedJsonMemoryStore(tmp_path / "memory.json")
            store.save({"notes": ["note secrète"], "compteur": 42})

        # Lecture brute du fichier — la valeur de "notes" doit être un blob base64
        raw = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
        assert isinstance(raw["notes"], str)
        # Doit être décodable en bytes et commencer par le magic header
        decoded = base64.b64decode(raw["notes"])
        assert decoded[:len(BLOB_HEADER)] == BLOB_HEADER
        # La clé "compteur" (non sensible) est en clair
        assert raw["compteur"] == 42

    def test_load_decrypts_transparent(self, tmp_path, engine_with_key):
        """Le chargement redonne les valeurs originales."""
        from context_engine.encrypted_memory_store import EncryptedJsonMemoryStore
        original = {"notes": ["note secrète"], "compteur": 42}
        with patch("context_engine.encrypted_memory_store.crypto_engine", engine_with_key):
            store = EncryptedJsonMemoryStore(tmp_path / "memory.json")
            store.save(original)
            loaded = store.load()
        assert loaded["notes"] == ["note secrète"]
        assert loaded["compteur"] == 42

    def test_migration_from_unencrypted_store(self, tmp_path, engine_with_key):
        """Les valeurs non chiffrées existantes sont lues sans erreur."""
        mem_path = tmp_path / "memory.json"
        mem_path.write_text(
            json.dumps({"notes": "note legacy", "prenom": "Carl"}),
            encoding="utf-8",
        )
        from context_engine.encrypted_memory_store import EncryptedJsonMemoryStore
        with patch("context_engine.encrypted_memory_store.crypto_engine", engine_with_key):
            store = EncryptedJsonMemoryStore(mem_path)
            loaded = store.load()
        # La valeur non chiffrée doit être retournée telle quelle
        assert loaded["notes"] == "note legacy"

    def test_disabled_engine_passthrough(self, tmp_path, engine_no_key):
        """Sans clé, le store se comporte comme JsonMemoryStore."""
        from context_engine.encrypted_memory_store import EncryptedJsonMemoryStore
        with patch("context_engine.encrypted_memory_store.crypto_engine", engine_no_key):
            store = EncryptedJsonMemoryStore(tmp_path / "memory.json")
            data = {"notes": ["donnée privée"], "compteur": 7}
            store.save(data)
            loaded = store.load()
        assert loaded == data


# ─── Tests outils publics DataShield ─────────────────────────────────────────

class TestDataShieldTools:
    def test_statut_chiffrement_actif(self, engine_with_key):
        with patch("datashield.tools.crypto_engine", engine_with_key):
            result = statut_chiffrement()
        assert "ACTIF" in result
        assert "AES-256-GCM" in result

    def test_statut_chiffrement_inactif_sans_cle(self, engine_no_key):
        with patch("datashield.tools.crypto_engine", engine_no_key):
            result = statut_chiffrement()
        assert "INACTIF" in result

    def test_chiffrer_dechiffrer_round_trip(self, engine_with_key):
        with patch("datashield.tools.crypto_engine", engine_with_key):
            blob = chiffrer_valeur("ma valeur secrète")
            assert blob != "ma valeur secrète"
            recovered = dechiffrer_valeur(blob)
        assert recovered == "ma valeur secrète"

    def test_chiffrer_valeur_sans_cle(self, engine_no_key):
        with patch("datashield.tools.crypto_engine", engine_no_key):
            result = chiffrer_valeur("test")
        assert "CHIFFREMENT INACTIF" in result

    def test_dechiffrer_valeur_non_blob(self, engine_with_key):
        """Une valeur non chiffrée doit être retournée telle quelle."""
        with patch("datashield.tools.crypto_engine", engine_with_key):
            result = dechiffrer_valeur("valeur en clair")
        assert result == "valeur en clair"


# ─── Test get_memory_store avec backend "encrypted" ──────────────────────────

class TestGetMemoryStoreEncrypted:
    def test_encrypted_backend_returns_encrypted_store(self, tmp_path):
        from context_engine.memory_store import get_memory_store, reset_memory_stores
        from context_engine.encrypted_memory_store import EncryptedJsonMemoryStore
        reset_memory_stores()
        with patch.dict(os.environ, {"JARVIS_MEMORY_BACKEND": "encrypted"}):
            store = get_memory_store()
        assert isinstance(store, EncryptedJsonMemoryStore)
        reset_memory_stores()
