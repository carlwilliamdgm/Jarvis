# interface_morphique/tools.py
"""Outils et façades publiques de capacités pour le module Interface Morphique (GreatOS Module 8)."""

from __future__ import annotations

from datashield.error_classification import resultat_erreur
from interface_morphique.browser_overlay import start_browser_overlay, stop_browser_overlay


def demarrer_overlay_navigation() -> str:
    """Démarre l'overlay visuel de navigation en temps réel."""
    try:
        result = start_browser_overlay()
        if result:
            return "Overlay de navigation démarré avec succès"
        else:
            return "L'overlay de navigation est déjà en cours d'exécution"
    except Exception as e:
        return resultat_erreur(f"Erreur lors du démarrage de l'overlay: {str(e)}", e)


def arreter_overlay_navigation() -> str:
    """Arrête l'overlay visuel de navigation."""
    try:
        stop_browser_overlay()
        return "Overlay de navigation arrêté"
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'arrêt de l'overlay: {str(e)}", e)

