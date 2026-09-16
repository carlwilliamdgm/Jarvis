# datashield/tools.py
"""Outils et façades publiques de capacités pour le module DataShield (GreatOS Module 6)."""

from __future__ import annotations

from datashield.defcon import DefconLevel, defcon
from datashield.error_classification import resultat_erreur


def obtenir_niveau_defcon() -> str:
    """Retourne le niveau DEFCON actuel et sa signification."""
    lvl = defcon.current_level
    descriptions = {
        5: "Nominal / standard",
        4: "Vigilance accrue",
        3: "Sécurisé (confirmation obligatoire pour commandes)",
        2: "Alerte haute (actions destructives bloquées)",
        1: "Confinement critique (verrouillage complet)",
    }
    desc = descriptions.get(lvl.value, "Inconnu")
    return f"Niveau DEFCON actuel : {lvl.name} ({lvl.value}) - {desc}"


def changer_niveau_defcon(niveau: int) -> str:
    """Modifie le niveau de sécurité DEFCON (1 à 5)."""
    try:
        val = int(niveau)
        if val not in {1, 2, 3, 4, 5}:
            return f"Niveau DEFCON invalide ({niveau}). Choisissez une valeur entre 1 et 5."
        nouveau = DefconLevel(val)
        defcon.set_level(nouveau)
        return f"Niveau DEFCON mis à jour avec succès : {nouveau.name} ({nouveau.value})"
    except Exception as e:
        return resultat_erreur(f"Erreur lors du changement DEFCON : {e}", e)

