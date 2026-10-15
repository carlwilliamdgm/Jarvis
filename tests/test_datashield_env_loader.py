from datashield.env_loader import supprimer_cle_datashield


def test_supprimer_cle_datashield_retire_toutes_les_copies_et_garde_le_reste(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GREATOS_ENV=production\nJARVIS_CRYPTO_KEY=example-one\nKEEP=value\nJARVIS_CRYPTO_KEY=example-two\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_CRYPTO_KEY", "example-one")

    supprimer_cle_datashield(env_file)

    assert env_file.read_text(encoding="utf-8") == "GREATOS_ENV=production\nKEEP=value\n"
    assert "JARVIS_CRYPTO_KEY" not in __import__("os").environ


def test_supprimer_cle_datashield_clears_process_env_when_file_has_no_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GREATOS_ENV=production\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CRYPTO_KEY", "ephemeral")

    supprimer_cle_datashield(env_file)

    assert env_file.read_text(encoding="utf-8") == "GREATOS_ENV=production\n"
    assert "JARVIS_CRYPTO_KEY" not in __import__("os").environ
