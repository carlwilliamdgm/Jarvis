"""Tool Registry - Registre central des capacités et outils de GreatOS (Core Intellect).

Fournit un registre neutre pour Core Intellect afin d'éviter tout couplage inversé
vers TaskFlow. Les modules d'exécution (TaskFlow, Interface Morphique, etc.) y enregistrent
leurs outils ou le registre se charge dynamiquement au premier accès.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

# Registre interne partagé
_OUTILS_REGISTRY: Dict[str, Callable[..., Any]] = {}


def enregistrer_outil(nom: str, fonction: Callable[..., Any]) -> None:
    """Enregistre un outil dans le registre central."""
    _OUTILS_REGISTRY[nom] = fonction


def enregistrer_outils(outils: Dict[str, Callable[..., Any]]) -> None:
    """Enregistre un dictionnaire d'outils dans le registre central."""
    _OUTILS_REGISTRY.update(outils)


def obtenir_outils() -> Dict[str, Callable[..., Any]]:
    """Retourne la copie ou l'accès au registre des outils disponibles.

    Si le registre est vide, effectue un chargement paresseux (lazy-load)
    depuis taskflow.tools pour garantir la rétrocompatibilité complète.
    """
    global _OUTILS_REGISTRY
    if not _OUTILS_REGISTRY:
        try:
            from taskflow.tools import OUTILS as _TASKFLOW_OUTILS
            _OUTILS_REGISTRY.update(_TASKFLOW_OUTILS)
        except (ImportError, Exception) as e:
            logger.debug("Chargement paresseux des outils taskflow: %s", e)
    return _OUTILS_REGISTRY


class _OutilsProxy(dict):
    """Proxy dictionnaire pour un accès paresseux transparent à OUTILS."""

    def __getitem__(self, key: str) -> Any:
        return obtenir_outils()[key]

    def __contains__(self, key: object) -> bool:
        return key in obtenir_outils()

    def __iter__(self):
        return iter(obtenir_outils())

    def __len__(self) -> int:
        return len(obtenir_outils())

    def get(self, key: str, default: Any = None) -> Any:
        return obtenir_outils().get(key, default)

    def items(self):
        return obtenir_outils().items()

    def keys(self):
        return obtenir_outils().keys()

    def values(self):
        return obtenir_outils().values()


# Instance proxy utilisable directement comme un dict : `outil in OUTILS` ou `OUTILS.items()`
OUTILS = _OutilsProxy()
