# syncsphere/tools.py
"""Outils et façades publiques de capacités pour le module SyncSphere (GreatOS Module 7)."""

from __future__ import annotations

import hashlib

from datashield.error_classification import resultat_erreur
from datashield.policy import evaluate_capability
from greatos_contracts import CapabilityExecution, CapabilityRequest, CapabilityStatus, RiskLevel, SecurityDecision
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
        chiffre_tag = " [🔒 Chiffré]" if snapshot_manager.est_chiffre(chemin) else " [🔓 Non chiffré]"
        return f"Snapshot GreatOS créé avec succès{chiffre_tag} : {chemin.name} ({chemin})"
    except Exception as e:
        return resultat_erreur(f"Erreur création snapshot : {e}", e)


def creer_snapshot_systeme_capability(nom: str = "", chiffrer: bool | None = None) -> CapabilityExecution:
    """Version dispatcher qui expose une compensation bornée au snapshot créé."""
    request = CapabilityRequest(
        capability="snapshots.create",
        arguments={"nom": nom},
        risk=RiskLevel.WRITE,
        resource="snapshot",
    )
    decision = evaluate_capability(request)
    if decision.decision == SecurityDecision.DENY:
        return CapabilityExecution(
            message=decision.reason,
            status=CapabilityStatus.DENIED,
            error_category="defcon_blocked",
            effect_status="none",
        )
    chemin = None
    try:
        chemin = snapshot_manager.creer_snapshot(nom=nom if nom else None, chiffrer=chiffrer)
        hasher = hashlib.sha256()
        with chemin.open("rb") as fichier:
            for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
                hasher.update(bloc)
        empreinte = hasher.hexdigest()

        def compenser() -> None:
            snapshot_manager.supprimer_snapshot_cree(chemin, empreinte)

        chiffre_tag = " [🔒 Chiffré]" if snapshot_manager.est_chiffre(chemin) else " [🔓 Non chiffré]"
        return CapabilityExecution(
            message=f"Snapshot GreatOS créé avec succès{chiffre_tag} : {chemin.name} ({chemin})",
            data={"snapshot": chemin.name, "path": str(chemin)},
            compensator=compenser,
            effect_status="compensable",
        )
    except Exception as exc:
        return CapabilityExecution(
            message=f"Erreur création snapshot : {exc}",
            status=CapabilityStatus.FAILED,
            error_category="erreur_technique_outil",
            data={"path": str(chemin)} if chemin is not None else {},
            effect_status="partial" if chemin is not None and chemin.exists() else "none",
        )


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
            chiffre_tag = " [🔒 Chiffré]" if s.get("chiffre") else " [🔓 Non chiffré]"
            lignes.append(f"- {s['nom']} ({taille_ko} Ko){chiffre_tag}")
        return "\n".join(lignes)
    except Exception as e:
        return resultat_erreur(f"Erreur liste snapshots : {e}", e)


