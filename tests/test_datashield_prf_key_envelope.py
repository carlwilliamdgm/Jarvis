from __future__ import annotations

from pathlib import Path

import pytest

from datashield import prf_key_envelope as envelope


PRF = bytes(range(32))


def test_round_trip_and_stable_prf_salt():
    prf_salt = b"s" * envelope.PRF_SALT_SIZE
    wrapped = envelope.wrap_secret(PRF, prf_salt, "master secret 🔐")
    assert envelope.unwrap_secret(PRF, prf_salt, wrapped) == "master secret 🔐"
    assert envelope.envelope_prf_salt(wrapped) == prf_salt
    assert len(wrapped) == (
        len(envelope.MAGIC) + 1 + envelope.PRF_SALT_SIZE
        + envelope.HKDF_SALT_SIZE + envelope.NONCE_SIZE
        + len("master secret 🔐".encode()) + envelope.TAG_SIZE
    )


@pytest.mark.parametrize("bad_prf", [b"", b"x" * 31, b"x" * 33, bytearray(32), None])
def test_prf_output_must_be_exactly_32_bytes(bad_prf):
    with pytest.raises(envelope.PrfEnvelopeError, match="32 octets"):
        envelope.create_envelope("master", bad_prf)


def test_wrong_prf_and_tampered_fields_fail_authentication():
    wrapped = envelope.create_envelope("master", PRF)
    with pytest.raises(envelope.PrfEnvelopeError, match="authentification"):
        envelope.unwrap_envelope(wrapped, b"z" * 32)

    changed = bytearray(wrapped)
    changed[-1] ^= 0x01
    with pytest.raises(envelope.PrfEnvelopeError, match="authentification"):
        envelope.unwrap_envelope(bytes(changed), PRF)


def test_wrong_stable_prf_salt_is_rejected():
    wrapped = envelope.wrap_secret(PRF, b"s" * 32, "master")
    with pytest.raises(envelope.PrfEnvelopeError, match="salt PRF"):
        envelope.unwrap_secret(PRF, b"t" * 32, wrapped)


def test_key_store_maps_to_deterministic_adjacent_path():
    key_store = Path("C:/GreatOS/DataShield/master-key.dpapi")
    assert envelope.envelope_path_for(key_store) == key_store.with_name("hello-key.wrap")


@pytest.mark.parametrize("bad", [b"", b"unknown!" + b"\0" * 80])
def test_short_and_unknown_formats_fail_closed(bad):
    with pytest.raises(envelope.PrfEnvelopeError):
        envelope.unwrap_envelope(bad, PRF)


def test_unsupported_version_fails_closed():
    wrapped = bytearray(envelope.create_envelope("master", PRF))
    wrapped[len(envelope.MAGIC)] = 99
    with pytest.raises(envelope.PrfEnvelopeError, match="Version"):
        envelope.unwrap_envelope(bytes(wrapped), PRF)


def test_wrong_salt_lengths_and_invalid_passphrase_are_rejected():
    with pytest.raises(envelope.PrfEnvelopeError, match="salt PRF"):
        envelope.create_envelope("master", PRF, prf_salt=b"x")
    with pytest.raises(envelope.PrfEnvelopeError, match="salt HKDF"):
        envelope.create_envelope("master", PRF, hkdf_salt=b"x")
    with pytest.raises(envelope.PrfEnvelopeError, match="nonce"):
        envelope.create_envelope("master", PRF, nonce=b"x")
    with pytest.raises(envelope.PrfEnvelopeError):
        envelope.create_envelope("", PRF)


def test_recovery_check_is_required_before_envelope_creation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "datashield.windows_key_store.verify_recovery_secret",
        lambda secret, path: secret == "master" and path == tmp_path / "master-key.dpapi",
    )
    wrapped = envelope.create_recovery_validated_envelope(
        "master", PRF, tmp_path / "master-key.dpapi"
    )
    assert envelope.unwrap_envelope(wrapped, PRF) == "master"

    with pytest.raises(envelope.PrfEnvelopeError, match="vérificateur de secours"):
        envelope.create_recovery_validated_envelope(
            "wrong", PRF, tmp_path / "master-key.dpapi"
        )


def test_atomic_writer_publishes_validated_file_and_refuses_replacement(monkeypatch, tmp_path):
    store = tmp_path / "master-key.dpapi"
    monkeypatch.setattr(
        "datashield.windows_key_store.verify_recovery_secret",
        lambda secret, path: secret == "master" and path == store,
    )
    target = tmp_path / "master-key.prf"
    wrapped = envelope.create_envelope("master", PRF)
    assert envelope.write_envelope_atomic(target, wrapped, "master", PRF, store) == target
    assert envelope.unwrap_envelope(target.read_bytes(), PRF) == "master"
    assert list(tmp_path.iterdir()) == [target]

    with pytest.raises(envelope.PrfEnvelopeError, match="existe déjà"):
        envelope.write_envelope_atomic(target, wrapped, "master", PRF, store)
    assert envelope.unwrap_envelope(target.read_bytes(), PRF) == "master"


def test_writer_rejects_bad_recovery_key_and_non_absolute_path(monkeypatch, tmp_path):
    store = tmp_path / "master-key.dpapi"
    monkeypatch.setattr(
        "datashield.windows_key_store.verify_recovery_secret", lambda _secret, _path: False
    )
    wrapped = envelope.create_envelope("master", PRF)
    with pytest.raises(envelope.PrfEnvelopeError, match="vérificateur de secours"):
        envelope.write_envelope_atomic(tmp_path / "x", wrapped, "master", PRF, store)
    with pytest.raises(envelope.PrfEnvelopeError, match="chemin"):
        envelope.write_envelope_atomic(Path("relative.prf"), wrapped, "master", PRF, store)

