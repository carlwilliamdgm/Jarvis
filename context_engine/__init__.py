# context_engine/__init__.py
"""Module Context Engine - Conscience contextuelle et mémoire (GreatOS Module 3)."""

from context_engine.memory_tools import (
    lire_contexte,
    lire_journal_agents,
    lire_notes,
    lire_preferences,
    lire_traces_capacites,
    memoriser_contexte,
    memoriser_preference,
    noter,
    oublier_contexte,
    oublier_preference,
)

__all__ = [
    "lire_contexte",
    "lire_journal_agents",
    "lire_notes",
    "lire_preferences",
    "lire_traces_capacites",
    "memoriser_contexte",
    "memoriser_preference",
    "noter",
    "oublier_contexte",
    "oublier_preference",
]

# Import optionnel du scheduler de consolidation (déplacé depuis service/)
try:
    from context_engine.consolidation_scheduler import ConsolidationScheduler  # noqa: F401
except ImportError:
    pass
