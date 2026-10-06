# core_intellect/__init__.py
"""Module Core Intellect - Cerveau décisionnel et moteur de réflexion (CDC GreatOS Module 4.2).

Rôle : Le moteur invisible qui analyse et décide.
- Analyse situationnelle holistique et évaluation multi-critères
- Décision, résolution de conflits et optimisation des workflows
- Routage déterministe d'intentions et validation d'arguments
- Ne gère PAS l'interface utilisateur directe (délégué à Jarvis)
"""

from core_intellect.cognitive_defense import (
    analyser_menace_cognitive,
    generer_reponse_neutralisation,
    CognitiveThreatSeverity,
    CognitiveThreatReport,
)
from core_intellect.intent_router import router_intention, IntentCategory, IntentRoute
from core_intellect.argument_validator import valider_et_corriger_arguments, ValidationResult

__all__ = [
    "analyser_menace_cognitive",
    "generer_reponse_neutralisation",
    "CognitiveThreatSeverity",
    "CognitiveThreatReport",
    "router_intention",
    "IntentCategory",
    "IntentRoute",
    "valider_et_corriger_arguments",
    "ValidationResult",
]
