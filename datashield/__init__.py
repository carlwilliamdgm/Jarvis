# datashield/__init__.py
"""Module DataShield - Sécurité multicouche, DEFCON et intégrité (GreatOS Module 6)."""

from datashield.tools import changer_niveau_defcon, obtenir_niveau_defcon

__all__ = ["changer_niveau_defcon", "obtenir_niveau_defcon"]
