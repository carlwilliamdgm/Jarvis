from __future__ import annotations

import os
from pathlib import Path

import pytest

from datashield import windows_key_store
from syncsphere import secure_spool as spool

_REAL_REQUIRE_WINDOWS = windows_key_store._require_windows


@pytest.fixture(autouse=True)
def fake_current_user_dpapi(monkeypatch):
    monkeypatch.setattr(windows_key_store, "_require_windows", lambda: None)

    def transform(data: bytes, *, protect: bool) -> bytes:
        # Test stand-in only. Production always calls native Windows DPAPI.
        return bytes(byte ^ 0xA5 for byte in data)

    monkeypatch.setattr(windows_key_store, "_dpapi_transform", transform)


def test_secure_spool_streams_authenticated_blocks_and_keeps_ciphertext_on_disk(tmp_path):
    source = (b"sensitive GreatOS state\x00" * 100_000) + b"end"
    writer = spool.SecureSpoolWriter.create(tmp_path, max_bytes=len(source))
    path = writer.path
    with writer:
        for offset in range(0, len(source), 123_457):
            writer.write(memoryview(source)[offset:offset + 123_457])

    raw = path.read_bytes()
    assert raw.startswith(spool.MAGIC)
    assert b"sensitive GreatOS state" not in raw
    assert writer.bytes_written == len(source)

    chunks = []
    with spool.SecureSpoolReader(path, max_bytes=len(source)) as reader:
        for chunk in reader.iter_chunks():
            assert len(chunk) <= spool.CHUNK_BYTES
            chunks.append(chunk)
        assert reader.verified
    assert b"".join(chunks) == source


def test_secure_spool_rejects_oversize_and_removes_aborted_ciphertext(tmp_path):
    writer = spool.SecureSpoolWriter.create(tmp_path, max_bytes=3)
    path = writer.path
    with pytest.raises(spool.SecureSpoolError, match="limite|taille maximale"):
        with writer:
            writer.write(b"four")
    assert not path.exists()


def test_large_single_write_is_processed_with_one_frame_of_plaintext_buffer(tmp_path):
    payload = b"z" * (spool.CHUNK_BYTES * 3 + 11)
    writer = spool.SecureSpoolWriter.create(tmp_path, max_bytes=len(payload))
    frame_sizes = []
    original_write_frame = writer._write_frame

    def bounded_write_frame(plaintext: bytes) -> None:
        assert len(plaintext) <= spool.CHUNK_BYTES
        frame_sizes.append(len(plaintext))
        original_write_frame(plaintext)

    writer._write_frame = bounded_write_frame
    with writer:
        assert writer.write(payload) == len(payload)
        assert len(writer._pending) <= spool.CHUNK_BYTES
    assert frame_sizes == [spool.CHUNK_BYTES] * 3 + [11]


@pytest.mark.parametrize("damage", ["ciphertext", "truncate", "trailing", "sequence"])
def test_reader_fails_closed_on_modified_or_incomplete_stream(tmp_path, damage):
    writer = spool.SecureSpoolWriter.create(tmp_path)
    path = writer.path
    with writer:
        writer.write(b"authenticated payload")
    raw = bytearray(path.read_bytes())
    if damage == "ciphertext":
        raw[-17] ^= 0x01
    elif damage == "truncate":
        del raw[-1:]
    elif damage == "trailing":
        raw.extend(b"x")
    else:
        wrapped_len_offset = spool._FIXED_HEADER.size - 4
        wrapped_len = int.from_bytes(raw[wrapped_len_offset:spool._FIXED_HEADER.size], "big")
        first_frame = spool._FIXED_HEADER.size + wrapped_len
        raw[first_frame] ^= 0x01
    path.write_bytes(raw)

    with pytest.raises(spool.SecureSpoolError):
        with spool.SecureSpoolReader(path) as reader:
            # A correctly tagged early block may be consumed, but context exit
            # must still detect truncation or tampering before the caller commits.
            reader.read(8)


def test_reader_rejects_unknown_header_and_wrong_dpapi_key(tmp_path, monkeypatch):
    writer = spool.SecureSpoolWriter.create(tmp_path)
    path = writer.path
    with writer:
        writer.write(b"payload")
    original = path.read_bytes()

    path.write_bytes(b"BADMAGIC" + original[len(spool.MAGIC):])
    with pytest.raises(spool.SecureSpoolError, match="Format"):
        spool.SecureSpoolReader(path)
    path.write_bytes(original)

    real_transform = windows_key_store._dpapi_transform
    monkeypatch.setattr(
        windows_key_store,
        "_dpapi_transform",
        lambda data, *, protect: b"x" * 32 if not protect else real_transform(data, protect=protect),
    )
    with pytest.raises(spool.SecureSpoolError, match="Authentification|AES-256"):
        with spool.SecureSpoolReader(path) as reader:
            reader.read()


def test_reader_limits_each_read_and_requires_authenticated_end(tmp_path):
    payload = b"a" * (spool.CHUNK_BYTES * 2 + 19)
    writer = spool.SecureSpoolWriter.create(tmp_path, max_bytes=len(payload))
    with writer:
        writer.write(payload)

    with spool.SecureSpoolReader(writer.path, max_bytes=len(payload)) as reader:
        assert len(reader.read(-1)) == spool.CHUNK_BYTES
        assert len(reader.read(100 * spool.CHUNK_BYTES)) == spool.CHUNK_BYTES
        assert len(reader.read()) == 19
        assert reader.read() == b""
        assert reader.verified


def test_context_exit_validates_remaining_stream_without_buffering_it(tmp_path, monkeypatch):
    payload = b"x" * (spool.CHUNK_BYTES * 3 + 7)
    writer = spool.SecureSpoolWriter.create(tmp_path, max_bytes=len(payload))
    with writer:
        writer.write(payload)

    original_next_frame = spool.SecureSpoolReader._next_frame
    buffered_during_validation = []

    def tracked_next_frame(reader, *, keep_plaintext=True):
        before = len(reader._buffer)
        result = original_next_frame(reader, keep_plaintext=keep_plaintext)
        if not keep_plaintext:
            assert len(reader._buffer) == before
            buffered_during_validation.append(len(reader._buffer))
        return result

    monkeypatch.setattr(spool.SecureSpoolReader, "_next_frame", tracked_next_frame)
    with spool.SecureSpoolReader(writer.path, max_bytes=len(payload)) as reader:
        assert reader.read(1) == b"x"
    assert buffered_during_validation


def test_reader_rejects_plaintext_over_configured_bound(tmp_path):
    writer = spool.SecureSpoolWriter.create(tmp_path, max_bytes=10)
    with writer:
        writer.write(b"1234567890")
    with pytest.raises(spool.SecureSpoolError, match="limite|taille maximale"):
        with spool.SecureSpoolReader(writer.path, max_bytes=9) as reader:
            reader.read()


def test_stale_cleanup_only_removes_owned_pattern_with_dead_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(spool.os, "getpid", lambda: 100)
    stale = tmp_path / ("greatos-spool-404-" + "a" * 32 + ".gsspool")
    current = tmp_path / ("greatos-spool-100-" + "b" * 32 + ".gsspool")
    live = tmp_path / ("greatos-spool-505-" + "c" * 32 + ".gsspool")
    unrelated = tmp_path / "other-file.gsspool"
    for path in (stale, current, live, unrelated):
        path.write_bytes(b"ciphertext")

    def fake_kill(pid: int, sig: int) -> None:
        if pid == 404:
            raise ProcessLookupError
        if pid == 505:
            return
        raise AssertionError(f"unexpected pid check: {pid}")

    monkeypatch.setattr(spool.os, "kill", fake_kill)
    removed = spool.cleanup_stale_spools(tmp_path)
    assert removed == [stale]
    assert not stale.exists()
    assert current.exists() and live.exists() and unrelated.exists()


def test_non_windows_production_guard_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(windows_key_store, "_require_windows", _REAL_REQUIRE_WINDOWS)
    monkeypatch.setattr(windows_key_store.os, "name", "posix")
    with pytest.raises(windows_key_store.KeyStoreError, match="uniquement sous Windows"):
        spool._require_windows()

