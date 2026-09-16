# syncsphere/tools.py
"""Outils et façades publiques de capacités pour le module SyncSphere (GreatOS Module 7)."""

from __future__ import annotations

from datashield.error_classification import resultat_erreur
from datashield.policy import evaluate_capability
from greatos_contracts import CapabilityRequest, RiskLevel, SecurityDecision
from syncsphere.snapshot import snapshot_manager


def creer_snapshot_systeme_tool(nom: str = "") -> str:
    """Crée une archive de sauvegarde locale (.gos) de l'état système GreatOS."""
    decision = evaluate_capability(CapabilityRequest(
        capability="snapshots.create",
        arguments={"nom": nom},
        risk=RiskLevel.WRITE,
        resource="snapshot",
    ))
    if decision.decision == SecurityDecision.DENY:
        return resultat_erreur(decision.reason, categorie="defcon_blocked")
    try:
        chemin = snapshot_manager.creer_snapshot(nom=nom if nom else None)
        return f"Snapshot GreatOS créé avec succès : {chemin.name} ({chemin})"
    except Exception as e:
        return resultat_erreur(f"Erreur création snapshot : {e}", e)


def lister_snapshots_systeme_tool() -> str:
    """Liste tous les snapshots d'état locaux (.gos) disponibles dans SyncSphere."""
    decision = evaluate_capability(CapabilityRequest(
        capability="snapshots.list",
        risk=RiskLevel.READ,
    ))
    if decision.decision == SecurityDecision.DENY:
        return resultat_erreur(decision.reason, categorie="defcon_blocked")
    try:
        snaps = snapshot_manager.lister_snapshots()
        if not snaps:
            return "Aucun snapshot disponible."
        lignes = ["=== SNAPSHOTS SYNCHSPHERE ==="]
        for s in snaps:
            taille_ko = round(s['taille_octets'] / 1024, 1)
            lignes.append(f"- {s['nom']} ({taille_ko} Ko)")
        return "\n".join(lignes)
    except Exception as e:
        return resultat_erreur(f"Erreur liste snapshots : {e}", e)


