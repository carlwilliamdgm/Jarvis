from pathlib import Path

import pytest

from scripts import setup_production


def test_legacy_env_key_is_wrapped_before_plaintext_entry_is_removed(tmp_path, monkeypatch):
    store = tmp_path / "master-key.dpapi"
    env_file = tmp_path / ".env"
    env_file.write_text("GREATOS_ENV=production\nJARVIS_CRYPTO_KEY=legacy-key\nKEEP=value\n", encoding="utf-8")
    persisted = {}

    monkeypatch.setattr(setup_production.os, "name", "nt")
    monkeypatch.setattr(setup_production, "key_store_path", lambda: store)

    def protect(value, path):
        persisted[path] = value
        path.write_bytes(b"wrapped")
        return path

    monkeypatch.setattr(setup_production, "protect_secret", protect)
    monkeypatch.setattr(setup_production, "unprotect_secret", lambda path: persisted[path])
    monkeypatch.setattr(setup_production, "restore_secret_store", lambda secret, path: True)
    monkeypatch.setenv("JARVIS_CRYPTO_KEY", "legacy-key")

    key, was_new = setup_production.provision_datashield_key(env_file)

    assert key == "legacy-key"
    assert was_new is True
    assert persisted[store] == "legacy-key"
    assert "JARVIS_CRYPTO_KEY" not in env_file.read_text(encoding="utf-8")
    assert "KEEP=value" in env_file.read_text(encoding="utf-8")
    assert "JARVIS_CRYPTO_KEY" not in setup_production.os.environ


def test_existing_protected_key_is_reused_without_overwrite(tmp_path, monkeypatch):
    store = tmp_path / "master-key.dpapi"
    store.write_bytes(b"existing")
    env_file = tmp_path / ".env"
    env_file.write_text("GREATOS_ENV=production\n", encoding="utf-8")
    protect_calls = []

    monkeypatch.setattr(setup_production.os, "name", "nt")
    monkeypatch.setattr(setup_production, "key_store_path", lambda: store)
    monkeypatch.setattr(setup_production, "protect_secret", lambda *args: protect_calls.append(args))
    monkeypatch.setattr(setup_production, "unprotect_secret", lambda path: "established-key")
    monkeypatch.setattr(setup_production, "restore_secret_store", lambda secret, path: True)
    monkeypatch.delenv("JARVIS_CRYPTO_KEY", raising=False)

    key, was_new = setup_production.provision_datashield_key(env_file)

    assert (key, was_new) == ("established-key", False)
    assert not protect_calls
    assert store.read_bytes() == b"existing"


def test_key_mismatch_fails_closed_without_changing_store_or_env(tmp_path, monkeypatch):
    store = tmp_path / "master-key.dpapi"
    store.write_bytes(b"existing")
    env_file = tmp_path / ".env"
    original = "JARVIS_CRYPTO_KEY=legacy-different\nKEEP=value\n"
    env_file.write_text(original, encoding="utf-8")

    monkeypatch.setattr(setup_production.os, "name", "nt")
    monkeypatch.setattr(setup_production, "key_store_path", lambda: store)
    monkeypatch.setattr(setup_production, "unprotect_secret", lambda path: "established-key")
    monkeypatch.setenv("JARVIS_CRYPTO_KEY", "legacy-different")

    with pytest.raises(RuntimeError, match="diffère"):
        setup_production.provision_datashield_key(env_file)

    assert env_file.read_text(encoding="utf-8") == original
    assert store.read_bytes() == b"existing"
    assert setup_production.os.environ["JARVIS_CRYPTO_KEY"] == "legacy-different"


def test_setup_never_recreates_dpapi_when_hello_envelope_exists(tmp_path, monkeypatch):
    store = tmp_path / "master-key.dpapi"
    envelope = tmp_path / "hello-key.wrap"
    envelope.write_bytes(b"existing-hello-envelope")
    env_file = tmp_path / ".env"
    env_file.write_text("GREATOS_ENV=production\n", encoding="utf-8")
    protect_calls = []
    monkeypatch.setattr(setup_production.os, "name", "nt")
    monkeypatch.setattr(setup_production, "key_store_path", lambda: store)
    monkeypatch.setattr(setup_production, "protect_secret", lambda *args: protect_calls.append(args))

    with pytest.raises(RuntimeError, match="liée à Windows Hello PRF"):
        setup_production.provision_datashield_key(env_file)

    assert not store.exists()
    assert not protect_calls
    assert env_file.read_text(encoding="utf-8") == "GREATOS_ENV=production\n"
