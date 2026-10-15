from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from datashield.windows_session import (
    WM_WTSSESSION_CHANGE,
    WTS_REMOTE_DISCONNECT,
    WindowsSessionMonitor,
    input_desktop_is_unlocked,
)
from interface_morphique import server
from core_intellect.event_bus import EventBus
from datashield.profile_gate import profile_execution_gate


@pytest.fixture(autouse=True)
def reset_session_gates():
    server.WINDOWS_SESSION_LOCKED.clear()
    profile_execution_gate.set_locked(False)
    server.event_bus.set_profile_locked(False)
    yield
    server.WINDOWS_SESSION_LOCKED.clear()
    profile_execution_gate.set_locked(False)
    server.event_bus.set_profile_locked(False)


def test_session_monitor_reports_only_state_transitions():
    transitions: list[tuple[str, str | None]] = []
    monitor = WindowsSessionMonitor(
        on_locked=lambda reason: transitions.append(("locked", reason)),
        on_unlocked=lambda: transitions.append(("unlocked", None)),
    )
    monitor._set_unlocked_state(False, "initial-locked")
    monitor._set_unlocked_state(True, "unlocked")
    monitor._set_unlocked_state(True, "duplicate-unlock")
    monitor._set_unlocked_state(False, "suspend")
    assert transitions == [("unlocked", None), ("locked", "suspend")]


def test_monitor_retries_transition_after_callback_failure():
    calls = []
    def unlock():
        calls.append("unlock")
        if len(calls) == 1:
            raise RuntimeError("temporary startup failure")
    monitor = WindowsSessionMonitor(lambda reason: None, unlock)
    try:
        monitor._set_unlocked_state(True, "first")
    except RuntimeError:
        pass
    monitor._set_unlocked_state(True, "retry")
    assert calls == ["unlock", "unlock"]
    assert monitor._reported_unlocked is True


def test_remote_disconnect_is_a_lock_transition():
    transitions = []
    monitor = WindowsSessionMonitor(
        on_locked=lambda reason: transitions.append(reason), on_unlocked=lambda: None
    )
    monitor._reported_unlocked = True
    monitor._window_proc(1, WM_WTSSESSION_CHANGE, WTS_REMOTE_DISCONNECT, 0)
    assert transitions == ["remote_disconnect"]


def test_input_desktop_detection_fails_closed_off_windows():
    with patch("datashield.windows_session.sys.platform", "linux"):
        assert input_desktop_is_unlocked() is False


def test_event_bus_drops_profile_payloads_until_explicit_unlock():
    bus = EventBus()
    local = bus.subscribe()
    broadcast = bus.subscribe_broadcast()
    bus.clear_sensitive_state()
    bus.bind(local)
    bus.emit("secret", {"value": "profile"})
    bus.emit_broadcast("alerte_proactive", {"value": "profile"})
    bus.unbind()
    assert local.empty()
    assert broadcast.empty()
    bus.set_profile_locked(False)
    bus.bind(local)
    bus.emit("safe", {"value": "unlocked"})
    bus.unbind()
    assert local.get_nowait()["type"] == "safe"


def test_broadcast_started_before_lock_is_drained_before_lock_returns():
    bus = EventBus()
    event_queue = bus.subscribe_broadcast()
    entered = threading.Event()
    release = threading.Event()
    original_put = event_queue.put
    def slow_put(item):
        entered.set()
        release.wait(timeout=3)
        original_put(item)
    event_queue.put = slow_put
    emitter = threading.Thread(target=bus.emit_broadcast, args=("profile", {"value": "sensitive"}))
    emitter.start()
    assert entered.wait(timeout=2)
    locker = threading.Thread(target=bus.clear_sensitive_state)
    locker.start()
    release.set()
    emitter.join(timeout=2)
    locker.join(timeout=2)
    assert not emitter.is_alive() and not locker.is_alive()
    assert event_queue.empty()


def test_lock_handler_gates_requests_before_runtime_teardown():
    server.WINDOWS_SESSION_LOCKED.clear()
    app = SimpleNamespace(state=SimpleNamespace())
    try:
        with patch.object(server, "_stop_profile_runtime") as stop:
            server._handle_windows_session_lock(app, "session_lock")
        assert server.WINDOWS_SESSION_LOCKED.is_set()
        stop.assert_called_once_with(app, "session_lock")
    finally:
        server.WINDOWS_SESSION_LOCKED.clear()


def test_unlock_handler_uses_current_user_dpapi_and_restarts_workers():
    app = SimpleNamespace(state=SimpleNamespace())
    locked = server.WINDOWS_SESSION_LOCKED
    engine = SimpleNamespace(is_enabled=False, is_hello_wrapped=False, dpapi_recovery_available=True,
                             unlock_from_key_store=lambda: None)
    def unlock_from_key_store():
        engine.is_enabled = True
    locked.set()
    try:
        with patch("datashield.crypto.crypto_engine", engine), \
             patch.object(engine, "unlock_from_key_store", side_effect=unlock_from_key_store) as unlock, \
             patch("datashield.windows_session.input_desktop_is_unlocked", return_value=True), \
             patch.object(server, "_start_runtime_services") as start:
            server._handle_windows_session_unlock(app)
        unlock.assert_called_once_with()
        assert not locked.is_set()
        start.assert_called_once_with(app, expected_generation=profile_execution_gate.generation)
    finally:
        locked.clear()
        profile_execution_gate.set_locked(False)


def test_unlock_waits_until_profile_workers_have_quiesced():
    app = SimpleNamespace(state=SimpleNamespace())
    server.WINDOWS_SESSION_LOCKED.set()
    try:
        with patch.object(server, "_profile_workers_pending", return_value=True):
            try:
                server._handle_windows_session_unlock(app)
            except RuntimeError as exc:
                assert "worker" in str(exc).lower() or "interaction" in str(exc).lower()
            else:
                raise AssertionError("La reprise doit attendre l'arrêt des workers du profil.")
        assert server.WINDOWS_SESSION_LOCKED.is_set()
    finally:
        server.WINDOWS_SESSION_LOCKED.clear()


def test_http_profile_routes_return_locked_while_windows_session_is_locked():
    from starlette.requests import Request

    async def call_next(_request):
        return SimpleNamespace(status_code=200)

    request = Request({"type": "http", "method": "GET", "path": "/jarvis/status", "headers": [], "query_string": b""})
    server.WINDOWS_SESSION_LOCKED.set()
    try:
        response = asyncio.run(server.require_datashield_unlock(request, call_next))
        assert response.status_code == 423
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.WINDOWS_SESSION_LOCKED.clear()


def test_http_profile_response_is_replaced_if_session_locks_mid_request():
    from starlette.requests import Request

    async def call_next(_request):
        server.WINDOWS_SESSION_LOCKED.set()
        return SimpleNamespace(status_code=200)

    request = Request({"type": "http", "method": "GET", "path": "/jarvis/status", "headers": [], "query_string": b""})
    server.WINDOWS_SESSION_LOCKED.clear()
    try:
        response = asyncio.run(server.require_datashield_unlock(request, call_next))
        assert response.status_code == 423
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.WINDOWS_SESSION_LOCKED.clear()


def test_capability_dispatch_refuses_actions_after_mid_request_lock():
    from greatos_capabilities import execute_capability

    calls = []
    profile_execution_gate.set_locked(True)
    server.WINDOWS_SESSION_LOCKED.set()
    try:
        result = execute_capability({"executer_commande": lambda **kwargs: calls.append(kwargs)},
                                    "executer_commande", {"commande": "whoami"})
        assert result.error_category == "profil_verrouille"
        assert calls == []
    finally:
        server.WINDOWS_SESSION_LOCKED.clear()


def test_capability_admission_is_atomic_and_tracks_inflight_effects():
    from greatos_capabilities import execute_capability

    entered = threading.Event()
    release = threading.Event()
    calls = []
    def slow_tool(**_kwargs):
        calls.append("started")
        entered.set()
        release.wait(timeout=5)
        return "finished"
    registry = {"executer_commande": slow_tool}
    active = threading.Thread(target=execute_capability, args=(registry, "executer_commande", {}))
    active.start()
    assert entered.wait(timeout=2)
    profile_execution_gate.set_locked(True)
    try:
        denied = execute_capability(registry, "executer_commande", {})
        assert denied.error_category == "profil_verrouille"
        assert calls == ["started"]
        assert profile_execution_gate.active_count == 1
    finally:
        release.set()
        active.join(timeout=3)
    assert not active.is_alive()
    assert profile_execution_gate.active_count == 0


def test_old_session_generation_cannot_reenter_after_quick_lock_unlock():
    generation = profile_execution_gate.generation
    profile_execution_gate.set_locked(True)
    profile_execution_gate.set_locked(False)
    with profile_execution_gate.admit(generation) as admitted:
        assert admitted is False
    with profile_execution_gate.admit(profile_execution_gate.generation) as admitted:
        assert admitted is True

