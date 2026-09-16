"""Contrats du noyau GreatOS entre les huit modules du CDC.

Ce fichier appartient au noyau d'intégration, pas à un neuvième module métier.
Il définit seulement le vocabulaire commun avec lequel les modules collaborent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    SYSTEM = "system"
    DESTRUCTIVE = "destructive"


class SecurityDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class CapabilityStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class CapabilityRequest:
    """Demande normalisée produite par l'orchestrateur pour un module propriétaire."""

    capability: str
    arguments: dict[str, Any] = field(default_factory=dict)
    risk: RiskLevel = RiskLevel.READ
    resource: str = ""
    requires_confirmation: bool = False
    irreversible: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    """Décision souveraine de DataShield ; aucun effet système n'est produit ici."""

    decision: SecurityDecision
    reason: str


@dataclass(frozen=True)
class CapabilityResult:
    """Résultat stable d'une capacité, indépendamment de son module propriétaire."""

    capability: str
    status: CapabilityStatus
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_category: str | None = None


@dataclass(frozen=True)
class PlanStep:
    """Étape individuelle d'un plan d'exécution généré par Core Intellect."""

    id: str
    capability: str
    arguments: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    preconditions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionPlan:
    """Plan complet d'exécution structuré en graphe d'étapes ordonnées."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

