# datashield/__init__.py
"""Module DataShield - Sécurité multicouche, DEFCON, chiffrement et intégrité (GreatOS Module 6)."""

from datashield.tools import (
    changer_niveau_defcon,
    chiffrer_valeur,
    dechiffrer_valeur,
    obtenir_niveau_defcon,
    statut_chiffrement,
)

__all__ = [
    "changer_niveau_defcon",
    "chiffrer_valeur",
    "dechiffrer_valeur",
    "obtenir_niveau_defcon",
    "statut_chiffrement",
]
