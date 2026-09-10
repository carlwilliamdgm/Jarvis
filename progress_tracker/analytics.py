# progress_tracker/analytics.py
"""Module d'analyse et calcul de métriques pour Progress Tracker (GreatOS)."""

from typing import Dict
from progress_tracker.goals import goal_manager, GoalStatus


def calculer_statistiques_globales() -> Dict:
    """Calcule le taux de complétion global et la distribution des statuts."""
    objectifs = goal_manager.lister_objectifs()
    total = len(objectifs)
    if total == 0:
        return {
            "total": 0,
            "termines": 0,
            "actifs": 0,
            "taux_completion": 0.0,
            "progression_moyenne": 0.0,
        }

    termines = sum(1 for g in objectifs if g.status == GoalStatus.COMPLETED)
    actifs = sum(1 for g in objectifs if g.status == GoalStatus.ACTIVE)
    progression_totale = sum(g.progression_pourcentage for g in objectifs)

    return {
        "total": total,
        "termines": termines,
        "actifs": actifs,
        "taux_completion": round((termines / total) * 100.0, 1),
        "progression_moyenne": round(progression_totale / total, 1),
    }
