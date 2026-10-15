"""Atomic admission gate for profile-backed capabilities during lock events."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Iterator


class ProfileExecutionGate:
    """Reject new capabilities after lock and track calls already admitted."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._locked = False
        self._active = 0
        self._active_action_steps = 0
        self._generation = 0
        self._local = threading.local()

    @property
    def active_count(self) -> int:
        with self._condition:
            return self._active

    @property
    def active_action_steps(self) -> int:
        """Number of admitted atomic actions that must drain before key teardown."""
        with self._condition:
            return self._active_action_steps

    @property
    def locked(self) -> bool:
        with self._condition:
            return self._locked

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    @property
    def current_action_admitted(self) -> bool:
        """Whether this thread is draining an action admitted before lock."""
        return getattr(self._local, "action_depth", 0) > 0

    def set_locked(self, locked: bool) -> None:
        with self._condition:
            if locked and not self._locked:
                self._generation += 1
            self._locked = locked
            self._condition.notify_all()

    def unlock_if_generation(self, expected_generation: int) -> bool:
        """Open admission only if no Windows lock transition happened meanwhile."""
        with self._condition:
            if self._generation != expected_generation or not self._locked:
                return False
            self._locked = False
            self._condition.notify_all()
            return True

    @contextmanager
    def admit(self, expected_generation: int | None = None) -> Iterator[bool]:
        with self._condition:
            nested_in_admitted_action = self.current_action_admitted
            admitted = nested_in_admitted_action or (
                not self._locked
                and (expected_generation is None or expected_generation == self._generation)
            )
            if admitted:
                self._active += 1
        try:
            yield admitted
        finally:
            if admitted:
                with self._condition:
                    self._active -= 1
                    self._condition.notify_all()

    @contextmanager
    def action_step(self, expected_generation: int | None = None) -> Iterator[bool]:
        """Admit one indivisible action and let it drain across a lock transition.

        Locking closes admission and advances the generation. An already-admitted
        action is not interrupted; callers must use the captured generation for
        later steps so a fast unlock cannot resume the old workflow.
        """
        with self._condition:
            nested_in_admitted_action = self.current_action_admitted
            admitted = nested_in_admitted_action or (
                not self._locked
                and (expected_generation is None or expected_generation == self._generation)
            )
            if admitted:
                self._active_action_steps += 1
                self._local.action_depth = getattr(self._local, "action_depth", 0) + 1
        try:
            yield admitted
        finally:
            if admitted:
                with self._condition:
                    self._active_action_steps -= 1
                    self._condition.notify_all()
                self._local.action_depth -= 1

    def wait_for_action_steps(self) -> None:
        """Wait until all actions admitted before a lock transition have drained."""
        with self._condition:
            self._condition.wait_for(lambda: self._active_action_steps == 0)


profile_execution_gate = ProfileExecutionGate()
