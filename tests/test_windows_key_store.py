from __future__ import annotations

from pathlib import Path

import pytest

from datashield import windows_key_store as store

_REAL_REQUIRE_WINDOWS = store._require_windows
_REAL_DPAPI_TRANSFORM = store._dpapi_transform


@pytest.fixture(autouse=True)
def fake_windows_dpapi(monkeypatch):
    monkeypatch.setattr(store, "_require_windows", lambda: None)

    def transform(data: bytes, *, protect: bool) -> bytes:
        # Test-only reversible stand-in; production always calls native DPAPI.
        return bytes(value ^ 0xA5 for value in data)

    monkeypatch.setattr(store, "_dpapi_transform", transform)


def test_default_path_uses_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv("GREATOS_KEY_STORE_PATH", raising=False)
    local_app_data = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    assert store.key_store_path() == local_app_data / "GreatOS" / "DataShield" / "master-key.dpapi"


def test_configured_path_must_be_absolute(monkeypatch):
    monkeypatch.setenv("GREATOS_KEY_STORE_PATH", "relative\\secret.dpapi")
    with pytest.raises(store.KeyStoreError):
        store.key_store_path()


def test_round_trip_utf8_and_verification(tmp_path):
    path = tmp_path / "nested" / "key.dpapi"
    assert store.protect_secret("clé 🔐", path) == path
    assert store.unprotect_secret(path) == "clé 🔐"
    assert store.verify_secret("clé 🔐", path)
    assert not store.verify_secret("autre", path)


def test_file_contains_only_wrapped_payload(tmp_path):
    path = tmp_path / "key.dpapi"
    store.protect_secret("high entropy secret", path)
    assert b"high entropy secret" not in path.read_bytes()


def test_manual_recovery_rebuilds_missing_or_corrupt_dpapi_store(tmp_path):
    path = tmp_path / "master-key.dpapi"
    store.protect_secret("recovery-secret", path)
    store.ensure_recovery_check("recovery-secret", path)
    path.unlink()

    assert store.restore_secret_store("recovery-secret", path)
    assert store.unprotect_secret(path) == "recovery-secret"

    path.write_bytes(b"corrupt DPAPI data")
    assert store.restore_secret_store("recovery-secret", path)
    assert store.unprotect_secret(path) == "recovery-secret"


def test_wrong_recovery_key_never_changes_dpapi_store(tmp_path):
    path = tmp_path / "master-key.dpapi"
    store.protect_secret("recovery-secret", path)
    store.ensure_recovery_check("recovery-secret", path)
    original = path.read_bytes()
    path.write_bytes(b"corrupt DPAPI data")

    assert not store.restore_secret_store("wrong-secret", path)
    assert path.read_bytes() == b"corrupt DPAPI data"
    assert original != path.read_bytes()


def test_existing_recovery_verifier_is_not_overwritten(tmp_path):
    path = tmp_path / "master-key.dpapi"
    store.protect_secret("recovery-secret", path)
    verifier = store.ensure_recovery_check("recovery-secret", path)
    original = verifier.read_bytes()

    with pytest.raises(store.KeyStoreError, match="ne correspond pas"):
        store.ensure_recovery_check("different-secret", path)
    assert verifier.read_bytes() == original


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_valid_dpapi_key_repairs_missing_or_corrupt_recovery_verifier(tmp_path, damage):
    path = tmp_path / "master-key.dpapi"
    store.protect_secret("recovery-secret", path)
    verifier = store.ensure_recovery_check("recovery-secret", path)
    if damage == "missing":
        verifier.unlink()
    else:
        verifier.write_text("tampered", encoding="ascii")

    assert store.restore_secret_store("recovery-secret", path)
    assert store.verify_recovery_secret("recovery-secret", path)


@pytest.mark.skipif(store.os.name != "nt", reason="CryptoEngine DPAPI unlock is Windows-only")
def test_crypto_engine_manual_unlock_uses_recovery_store(tmp_path):
    from datashield.crypto import CryptoEngine
    import threading

    path = tmp_path / "master-key.dpapi"
    store.protect_secret("recovery-secret", path)
    store.ensure_recovery_check("recovery-secret", path)
    engine = CryptoEngine.__new__(CryptoEngine)
    engine._lock = threading.Lock()
    engine._passphrase = None
    engine._protected_key_path = path

    engine.unlock_with_manual_key("recovery-secret")
    assert engine.is_enabled
    assert engine.decrypt(engine.encrypt("recovery self-check")) == "recovery self-check"
    engine.lock()


@pytest.mark.skipif(store.os.name != "nt", reason="native DPAPI is Windows-only")
def test_native_windows_dpapi_round_trip(tmp_path, monkeypatch):
    with monkeypatch.context() as native:
        native.setattr(store, "_dpapi_transform", _REAL_DPAPI_TRANSFORM)
        native.setattr(store, "_require_windows", _REAL_REQUIRE_WINDOWS)
        path = tmp_path / "native-key.dpapi"
        store.protect_secret("native-test-secret", path)
        assert store.unprotect_secret(path) == "native-test-secret"


def test_invalid_or_tampered_format_fails_closed(tmp_path):
    path = tmp_path / "key.dpapi"
    path.write_bytes(b"unknown format")
    with pytest.raises(store.KeyStoreError):
        store.unprotect_secret(path)
    assert not store.verify_secret("anything", path)


def test_dpapi_failure_does_not_replace_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "key.dpapi"
    path.write_bytes(b"previous ciphertext")

    def fail_transform(_data: bytes, *, protect: bool) -> bytes:
        raise store.KeyStoreError("mock DPAPI failure")

    monkeypatch.setattr(store, "_dpapi_transform", fail_transform)
    with pytest.raises(store.KeyStoreError):
        store.protect_secret("new secret", path)
    assert path.read_bytes() == b"previous ciphertext"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("secret", ["", "contains\x00nul", "\ud800"])
def test_invalid_secret_is_rejected(secret, tmp_path):
    with pytest.raises(store.KeyStoreError):
        store.protect_secret(secret, tmp_path / "key.dpapi")


def test_non_windows_runtime_fails_closed(monkeypatch):
    monkeypatch.setattr(store.os, "name", "posix")
    with pytest.raises(store.KeyStoreError, match="uniquement sous Windows"):
        _REAL_REQUIRE_WINDOWS()

