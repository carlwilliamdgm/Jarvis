"""DataShield transitions from legacy Hello envelope to Windows-account DPAPI."""

import base64
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from datashield.crypto import CryptoEngine
from datashield.prf_key_envelope import create_envelope


@pytest.fixture
def engine_and_paths(tmp_path, monkeypatch):
    store = tmp_path / "master-key.dpapi"
    hello = store.with_name("hello-key.wrap")
    key = "master-passphrase"
    prf_bytes = bytes(range(32))
    encoded = base64.urlsafe_b64encode(prf_bytes).rstrip(b"=").decode("ascii")
    salt = bytes(range(32, 64))
    engine = CryptoEngine.__new__(CryptoEngine)
    engine._lock = threading.Lock()
    engine._passphrase = None
    engine._protected_key_path = None
    engine._hello_envelope_path = None
    monkeypatch.setattr("datashield.crypto.os.name", "nt")
    monkeypatch.setattr("datashield.windows_key_store.key_store_path", lambda: store)
    return engine, store, hello, key, prf_bytes, encoded, salt


def test_hello_migration_is_rejected_under_windows_session_policy(engine_and_paths):
    engine, store, *_ = engine_and_paths
    with pytest.raises(RuntimeError, match="DPAPI CurrentUser"):
        engine.migrate_to_hello("A" * 43, bytes(32))
    assert not store.exists()


def test_valid_dpapi_takes_precedence_while_hello_envelope_is_retained(engine_and_paths, monkeypatch):
    engine, store, hello, key, prf_bytes, _encoded, _salt = engine_and_paths
    store.write_bytes(b"dpapi-ciphertext")
    hello.write_bytes(create_envelope(key, prf_bytes))
    monkeypatch.setattr("datashield.windows_key_store.unprotect_secret", lambda _path: key)

    engine._load_passphrase()

    assert engine._protected_key_path == store
    assert engine._hello_envelope_path == hello
    assert not engine.is_hello_wrapped
    assert engine.is_locked
    assert hello.exists()


def test_manual_recovery_from_hello_only_creates_dpapi_and_retains_envelope(engine_and_paths, monkeypatch):
    engine, store, hello, key, prf_bytes, _encoded, _salt = engine_and_paths
    hello.write_bytes(create_envelope(key, prf_bytes))
    engine._hello_envelope_path = hello
    monkeypatch.setattr("datashield.windows_key_store.verify_recovery_secret", lambda secret, _path: secret == key)
    monkeypatch.setattr("datashield.windows_key_store.restore_secret_store", lambda secret, path: secret == key and path == store)
    monkeypatch.setattr("datashield.windows_key_store.unprotect_secret", lambda _path: key)

    engine.unlock_with_manual_key(key)

    assert engine.is_enabled
    assert engine._protected_key_path == store
    assert hello.exists()


def test_hello_unlock_restores_dpapi_only_after_verified_round_trip(engine_and_paths, monkeypatch):
    engine, store, hello, key, prf_bytes, encoded, _salt = engine_and_paths
    hello.write_bytes(create_envelope(key, prf_bytes))
    engine._hello_envelope_path = hello
    monkeypatch.setattr("datashield.windows_key_store.ensure_recovery_check", lambda _secret, _path: None)
    monkeypatch.setattr("datashield.windows_key_store.protect_secret", lambda _secret, path: path.write_bytes(b"new-dpapi"))
    monkeypatch.setattr("datashield.windows_key_store.unprotect_secret", lambda _path: key)

    engine.unlock_with_hello_prf(encoded)

    assert engine.is_enabled
    assert engine._protected_key_path == store
    assert store.read_bytes() == b"new-dpapi"
    assert hello.exists()


def test_hello_unlock_does_not_unlock_when_dpapi_readback_differs(engine_and_paths, monkeypatch):
    engine, store, hello, key, prf_bytes, encoded, _salt = engine_and_paths
    hello.write_bytes(create_envelope(key, prf_bytes))
    engine._hello_envelope_path = hello
    monkeypatch.setattr("datashield.windows_key_store.ensure_recovery_check", lambda _secret, _path: None)
    monkeypatch.setattr("datashield.windows_key_store.protect_secret", lambda _secret, path: path.write_bytes(b"new-dpapi"))
    monkeypatch.setattr("datashield.windows_key_store.unprotect_secret", lambda _path: "different-key")

    with pytest.raises(RuntimeError, match="validation"):
        engine.unlock_with_hello_prf(encoded)
    assert not engine.is_enabled
    assert hello.exists()


def test_prf_output_encoding_is_strict(engine_and_paths):
    engine, *_ = engine_and_paths
    for malformed in ("", "A" * 42, "A" * 42 + "=", "*" * 43):
        with pytest.raises(ValueError):
            engine._decode_prf_output(malformed)
