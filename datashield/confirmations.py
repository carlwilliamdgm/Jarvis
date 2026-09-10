"""Confirmation handlers shared by the console and streaming interfaces.

Tools remain synchronous.  A streaming request can therefore wait for a user
decision while its SSE connection stays open; the HTTP confirmation endpoint
resolves that wait from another request.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Event, RLock
from typing import Callable, Iterator
from uuid import uuid4


@dataclass
class PendingConfirmation:
    action_id: str
    session_id: str
    description: str
    expires_at: datetime
    resolved: Event = field(default_factory=Event)
    decision: bool | None = None


class ConfirmationManager:
    """Owns pending streaming confirmations for this local Jarvis process."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingConfirmation] = {}
        self._lock = RLock()

    def wait_for_decision(
        self,
        session_id: str,
        description: str,
        emit: Callable[[str, dict], None],
        timeout_seconds: int = 120,
    ) -> bool:
        action_id = uuid4().hex
        pending = PendingConfirmation(
            action_id=action_id,
            session_id=session_id,
            description=description,
            expires_at=datetime.now() + timedelta(seconds=timeout_seconds),
        )
        with self._lock:
            self._purge_expired_locked()
            self._pending[action_id] = pending

        emit(
            "confirmation_required",
            {
                "action_id": action_id,
                "description": description,
                "expires_at": pending.expires_at.isoformat(),
            },
        )

        pending.resolved.wait(timeout=timeout_seconds)
        with self._lock:
            self._pending.pop(action_id, None)
        return pending.decision is True

    def resolve(self, session_id: str, action_id: str, confirmed: bool) -> str:
        with self._lock:
            self._purge_expired_locked()
            pending = self._pending.get(action_id)
            if pending is None:
                return "not_found"
            if pending.session_id != session_id:
                return "wrong_session"
            if pending.decision is not None:
                return "already_resolved"

            pending.decision = confirmed
            pending.resolved.set()
            return "resolved"

    def _purge_expired_locked(self) -> None:
        now = datetime.now()
        expired = [
            action_id
            for action_id, pending in self._pending.items()
            if pending.expires_at <= now and not pending.resolved.is_set()
        ]
        for action_id in expired:
            pending = self._pending[action_id]
            pending.decision = False
            pending.resolved.set()


class StreamingConfirmationHandler:
    def __init__(self, session_id: str, emit: Callable[[str, dict], None]) -> None:
        self._session_id = session_id
        self._emit = emit

    def confirm(self, description: str) -> bool:
        return confirmation_manager.wait_for_decision(
            session_id=self._session_id,
            description=description,
            emit=self._emit,
        )


_confirmation_handler: ContextVar[StreamingConfirmationHandler | None] = ContextVar(
    "jarvis_confirmation_handler",
    default=None,
)
confirmation_manager = ConfirmationManager()


@contextmanager
def use_confirmation_handler(handler: StreamingConfirmationHandler) -> Iterator[None]:
    token = _confirmation_handler.set(handler)
    try:
        yield
    finally:
        _confirmation_handler.reset(token)


def request_streaming_confirmation(description: str) -> bool | None:
    """Return a decision for a streaming context, or ``None`` for console use."""
    handler = _confirmation_handler.get()
    return handler.confirm(description) if handler is not None else None
