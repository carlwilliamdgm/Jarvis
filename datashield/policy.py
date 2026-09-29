"""Moteur central de décision de sécurité pour les capacités GreatOS.

Intègre :
- Contrôle de provenance (Taint Analysis) : blocage des injections externes.
- Détection des techniques cyber (MITRE ATT&CK) : sabotage, vol de ruches, LOLBins.
- Désobfuscation et confirmation transparente pour l'utilisateur légitime.
- Niveaux d'urgence DEFCON (1 à 5).
"""

from __future__ import annotations

from greatos_contracts import CapabilityRequest, PolicyDecision, RequestOrigin, RiskLevel, SecurityDecision
from datashield.defcon import DefconLevel, defcon
from datashield.safety import est_mode_stark_actif
from datashield.threat_analyzer import ThreatSeverity, analyser_commande_systeme


def evaluate_capability(request: CapabilityRequest) -> PolicyDecision:
    """Retourne allow, confirm ou deny sans exécuter la capacité.

    Les modules propriétaires classent leur opération (risque, irréversibilité,
    besoin de confirmation, provenance). DataShield applique ensuite une politique
    unique et souveraine.
    """
    # 1. Frontière de confiance (Taint Analysis / Anti-Injection externe)
    # Un flux issu du Web ou d'un doc externe n'a JAMAIS le droit de commander l'OS ou de détruire
    if request.origin == RequestOrigin.EXTERNAL:
        if request.risk in (RiskLevel.SYSTEM, RiskLevel.DESTRUCTIVE):
            return PolicyDecision(
                SecurityDecision.DENY,
                "Action système/destructive bloquée : ordre émis depuis une source externe non fiable (protection anti-prompt injection).",
            )
        if request.risk == RiskLevel.WRITE:
            return PolicyDecision(
                SecurityDecision.CONFIRM,
                f"Écriture demandée depuis une source externe pour : {request.resource or 'ressource'}.",
            )

    # 2. Action irréversible déclarée
    if request.irreversible:
        return PolicyDecision(
            SecurityDecision.DENY,
            "Action irréversible bloquée par la politique de sécurité.",
        )

    # 3. Analyse de cyber-menaces sur les commandes système
    is_system = request.risk == RiskLevel.SYSTEM
    is_destructive = request.risk == RiskLevel.DESTRUCTIVE
    is_write = request.risk == RiskLevel.WRITE

    if is_system or request.capability in ("system.execute_command", "executer_commande"):
        commande = str(
            request.arguments.get("commande", "")
            or request.arguments.get("command", "")
            or request.resource
            or ""
        )
        if commande:
            threat = analyser_commande_systeme(commande)
            if threat.has_threat:
                # Menace critique absolue (sabotage ransomware, vol de ruche SAM)
                if threat.severity == ThreatSeverity.CRITICAL:
                    return PolicyDecision(
                        SecurityDecision.DENY,
                        f"Commande bloquée par DataShield (Menace critique : {threat.reason}).",
                    )
                # Menace élevée ou code camouflé (Base64) :
                # Pour l'utilisateur légitime, on ne bloque pas brutalement mais on
                # exige une confirmation avec affichage du code démasqué !
                if not est_mode_stark_actif():
                    detail = threat.reason
                    if threat.deobfuscated_payload:
                        apercu = threat.deobfuscated_payload[:80]
                        detail += f" [Contenu désobfusqué : {apercu}]"
                    return PolicyDecision(
                        SecurityDecision.CONFIRM,
                        f"Confirmation requise par DataShield : {detail}.",
                    )

    # 4. Politique d'urgence DEFCON
    level = defcon.current_level
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
