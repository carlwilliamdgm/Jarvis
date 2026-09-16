"""Moteur central de décision de sécurité pour les capacités GreatOS."""

from __future__ import annotations

from greatos_contracts import CapabilityRequest, PolicyDecision, RiskLevel, SecurityDecision
from datashield.defcon import DefconLevel, defcon
from datashield.safety import est_mode_stark_actif


def evaluate_capability(request: CapabilityRequest) -> PolicyDecision:
    """Retourne allow, confirm ou deny sans exécuter la capacité.

    Les modules propriétaires classent leur opération (risque, irréversibilité,
    besoin de confirmation). DataShield applique ensuite une politique unique,
    ce qui évite que TaskFlow, SyncSphere ou une interface interprètent chacun
    DEFCON différemment.
    """
    if request.irreversible:
        return PolicyDecision(
            SecurityDecision.DENY,
            "Action irréversible bloquée par la politique de sécurité.",
        )

    level = defcon.current_level
    is_system = request.risk == RiskLevel.SYSTEM
    is_destructive = request.risk == RiskLevel.DESTRUCTIVE
    is_write = request.risk == RiskLevel.WRITE

    if level == DefconLevel.DEFCON_1:
        return PolicyDecision(SecurityDecision.DENY, "Action bloquée par DEFCON 1.")
    if level == DefconLevel.DEFCON_2 and (is_system or is_destructive):
        return PolicyDecision(SecurityDecision.DENY, "Action bloquée par DEFCON 2.")
    if level == DefconLevel.DEFCON_2 and is_write and not est_mode_stark_actif():
        return PolicyDecision(SecurityDecision.CONFIRM, "DEFCON 2 exige une confirmation pour les opérations d'écriture.")
    if level == DefconLevel.DEFCON_3 and is_system:
        return PolicyDecision(SecurityDecision.CONFIRM, "DEFCON 3 exige une confirmation pour les commandes système.")
    if request.requires_confirmation and not est_mode_stark_actif():
        raison = f"Confirmation requise pour : {request.resource}" if request.resource else "Cette capacité cible une zone protégée."
        return PolicyDecision(SecurityDecision.CONFIRM, raison)
    return PolicyDecision(SecurityDecision.ALLOW, "Capacité autorisée par DataShield.")

