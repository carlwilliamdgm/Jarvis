# core/adapters.py
"""Adapter layer for GreatOS modularization.
Provides abstract interfaces for core components and legacy wrappers that
delegate to the existing implementation in the repository.
This allows new implementations to be swapped in without touching the rest
of the codebase.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Protocol, ContextManager

# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------

class IConversationEngine(Protocol):
    """High‑level orchestrator for a user interaction.
    Takes the current memory, history and a raw user message and returns the
    final assistant response (string)."""

    def process(self, message: str, memory: dict, history: List[dict]) -> str:
        ...

class IMemoryProvider(Protocol):
    """Persistence layer for the conversation‑wide memory.
    The implementation may be JSON, SQLite, encrypted DB, etc.
    """

    def load(self) -> dict:
        ...

    def save(self, data: dict) -> None:
        ...

    def transaction(self) -> ContextManager[dict]:
        """Return a context manager yielding a mutable copy of the memory.
        On exit the (potentially modified) memory is persisted atomically.
        """
        ...

class IIntentResolver(Protocol):
    """Decision engine that maps a user message + memory to a list of actions.
    The default implementation is a simple rule‑based stub; a future ML model
    can be plugged in without changing callers.
    """

    def resolve(self, message: str, memory: dict) -> List[Dict[str, Any]]:
        ...

# ---------------------------------------------------------------------------
# Legacy adapters – thin wrappers around the existing code
# ---------------------------------------------------------------------------

# The repository already provides concrete functions for memory handling in
# core/memory.py / core/memory_store.py.  We import them and expose the same
# API required by the protocols.

from core.memory import (
    charger_memoire as _legacy_load,
    sauvegarder_memoire as _legacy_save,
    transaction as _legacy_transaction,
)

class LegacyMemoryProvider:
    """Adapter that forwards calls to the original memory functions."""

    def load(self) -> dict:
        return _legacy_load()

    def save(self, data: dict) -> None:
        _legacy_save(data)

    def transaction(self):  # type: ignore[override]
        return _legacy_transaction()

# The original Jarvis orchestrator lives in jarvis.py as function
# `executer_interaction_utilisateur` (used by the API).  We wrap it.

from jarvis import executer_interaction_utilisateur as _legacy_process

class LegacyConversationEngine:
    """Adapter delegating to the historic `executer_interaction_utilisateur`.
    The signature matches IConversationEngine.process.
    """

    def process(self, message: str, memory: dict, history: List[dict]) -> str:
        # The legacy function expects the full memory dict and the history list.
        # It returns the final textual response.
        return _legacy_process(message, memory, history)

# Intent resolver – for now we expose a stub that simply forwards to the
# existing `interpreter_objectif` (core/intellect) if available, otherwise
# returns an empty list.

try:
    from core.intellect import interpreter_objectif as _legacy_resolve
except Exception:  # pragma: no cover – fallback if module missing
    _legacy_resolve = None

class LegacyIntentResolver:
    def resolve(self, message: str, memory: dict) -> List[Dict[str, Any]]:
        if _legacy_resolve:
            result = _legacy_resolve(message, memory, [])
            return result.get("actions", [])
        return []

# Export a singleton registry that the rest of the code can import.

memory_provider: IMemoryProvider = LegacyMemoryProvider()
conversation_engine: IConversationEngine = LegacyConversationEngine()
intent_resolver: IIntentResolver = LegacyIntentResolver()

# ---------------------------------------------------------------------------
# Helper to swap implementations (used by feature flags)
# ---------------------------------------------------------------------------

def set_memory_provider(provider: IMemoryProvider) -> None:
    """Replace the global memory provider – used by feature flags."""
    global memory_provider
    memory_provider = provider

def set_conversation_engine(engine: IConversationEngine) -> None:
    """Replace the global conversation engine – used by feature flags."""
    global conversation_engine
    conversation_engine = engine

def set_intent_resolver(resolver: IIntentResolver) -> None:
    """Replace the global intent resolver – used by feature flags."""
    global intent_resolver
    intent_resolver = resolver
