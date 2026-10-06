# jarvis/personality.py
"""Shim de rétrocompatibilité — le module a été déplacé vers core_intellect.

Ce fichier existe uniquement pour ne pas casser d'éventuelles références externes.
Utiliser directement : from core_intellect.personality import ...
"""
from core_intellect.personality import (  # noqa: F401
    PERSONNALITE_BASE,
    obtenir_personnalite_actuelle,
    ajuster_personnalite,
    adapter_ton_contextuel,
    memoriser_preference_communication,
    analyser_preferences_communication,
    generer_prompt_personnalite,
    evoluer_personnalite,
    obtenir_rapport_personnalite,
    reinitialiser_personnalite,
)
