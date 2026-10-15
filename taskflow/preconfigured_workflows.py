"""TaskFlow - Workflows préconfigurés avec arrêt et compensation explicite."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import time
from typing import Any, Callable, Dict, List
from uuid import uuid4


WORKFLOWS_CATALOGUE = {
    "session_dev": {
        "nom": "Session d'Ingénierie & Dev",
        "description": "Prépare l'environnement de développement, vérifie git et l'état de la machine.",
        "etapes": ["verifier_git", "inspecter_ressources", "activer_focus"],
    },
    "nettoyage_systeme": {
        "nom": "Nettoyage & Maintenance Système",
        "description": "Purge les caches temporaires, vérifie l'espace disque et optimise le stockage.",
        "etapes": ["purgers_pyc", "analyser_disque"],
    },
    "sauvegarde_securisee": {
        "nom": "Sauvegarde Locale Chiffrée",
        "description": "Génère un snapshot d'état chiffré AES-256 pour sauvegarde souveraine.",
        "etapes": ["creer_snapshot", "verifier_integrite"],
    },
    "synthese_projet": {
        "nom": "Synthèse du Projet & Apprentissages",
        "description": "Extrait les dernières sessions enregistrées et le statut des objectifs.",
        "etapes": ["lire_journal_sessions", "analyser_objectifs"],
    },
}


@dataclass(frozen=True)
class _StepOutcome:
    details: str
    compensation: Callable[[], None] | None = None
    effect_applied: bool = False


class _StepFailure(RuntimeError):
    def __init__(self, message: str, effects: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.effects = effects or []


def _executer_etapes(etapes: list[tuple[str, Callable[[], _StepOutcome]]]) -> dict[str, Any]:
    """Arrête au premier échec et exécute les compensations sûres en ordre inverse."""
    resultats: list[dict[str, str]] = []
    compensations: list[tuple[str, Callable[[], None]]] = []
    effets_non_annules: list[dict[str, str]] = []
    compensation_results: list[dict[str, str]] = []
    failed = False

    for step_id, action in etapes:
        try:
            outcome = action()
        except _StepFailure as exc:
            resultats.append({"etape": step_id, "statut": "erreur", "details": str(exc)})
            effets_non_annules.extend(exc.effects)
            failed = True
            break
        except Exception as exc:
            resultats.append({"etape": step_id, "statut": "erreur", "details": f"{type(exc).__name__}: {exc}"})
            failed = True
            break

        resultats.append({"etape": step_id, "statut": "ok", "details": outcome.details})
        if outcome.compensation is not None:
            compensations.append((step_id, outcome.compensation))
        elif outcome.effect_applied:
            effets_non_annules.append({
                "etape": step_id,
                "details": "Effet réalisé sans compensation sûre déclarée.",
            })

    if failed:
        for step_id, compensate in reversed(compensations):
            try:
                compensate()
                compensation_results.append({"etape": step_id, "statut": "annule"})
            except Exception as exc:
                compensation_results.append({"etape": step_id, "statut": "echec", "details": f"{type(exc).__name__}: {exc}"})
                effets_non_annules.append({
                    "etape": step_id,
                    "details": f"La compensation a échoué : {type(exc).__name__}: {exc}",
                })

    if not failed:
        rollback_status = "not_required"
    elif effets_non_annules or any(item["statut"] == "echec" for item in compensation_results):
        rollback_status = "partial"
    elif compensation_results:
        rollback_status = "completed"
    else:
        rollback_status = "not_required"

    return {
        "etapes": resultats,
        "succes": not failed,
        "rollback": {"statut": rollback_status, "etapes": compensation_results},
        "effets_non_annules": effets_non_annules,
    }


def lister_workflows_preconfigures() -> Dict[str, Any]:
    """Retourne la liste des workflows disponibles avec leurs étapes."""
    return WORKFLOWS_CATALOGUE


def executer_workflow_preconfigure(identifiant: str) -> Dict[str, Any]:
    """Exécute un workflow; arrête au premier échec et compense les effets déclarés réversibles."""
    if identifiant not in WORKFLOWS_CATALOGUE:
        return {
            "workflow": identifiant,
            "succes": False,
            "erreur": f"Workflow '{identifiant}' inconnu. Disponibles : {list(WORKFLOWS_CATALOGUE.keys())}",
            "rollback": {"statut": "not_required", "etapes": []},
            "effets_non_annules": [],
        }

    start = time.perf_counter()
    if identifiant == "session_dev":
        def verifier_git() -> _StepOutcome:
            proc = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=3, check=True)
            return _StepOutcome(f"{len(proc.stdout.splitlines())} fichiers modifiés")

        def inspecter_ressources() -> _StepOutcome:
            from context_engine.four_dimensions import capturer_contexte_quadridimensionnel
            context = capturer_contexte_quadridimensionnel()
            return _StepOutcome(f"CPU: {context.operationnel.cpu_percent}%, RAM: {context.operationnel.ram_percent}%")

        def activer_focus() -> _StepOutcome:
            from interface_morphique.context_switcher import get_morphic_engine
            try:
                get_morphic_engine().notifier_evenement("dev_session_started", {})
            except Exception as exc:
                raise _StepFailure(
                    f"Le signal focus a échoué : {type(exc).__name__}: {exc}",
                    [{"etape": "activer_focus", "details": "État du signal inconnu après l’échec."}],
                ) from exc
            return _StepOutcome("Signal de session focus émis", effect_applied=True)

        steps = [("verifier_git", verifier_git), ("inspecter_ressources", inspecter_ressources), ("activer_focus", activer_focus)]

    elif identifiant == "nettoyage_systeme":
        def purger_pyc() -> _StepOutcome:
            from pathlib import Path
            deleted = 0
            try:
                for path in Path(".").rglob("*.pyc"):
                    path.unlink()
                    deleted += 1
            except Exception as exc:
                effects = ([{"etape": "purgers_pyc", "details": f"{deleted} fichiers supprimés avant l’erreur."}] if deleted else [])
                raise _StepFailure(f"Suppression interrompue après {deleted} fichiers : {type(exc).__name__}: {exc}", effects) from exc
            return _StepOutcome(f"{deleted} fichiers .pyc purgés", effect_applied=deleted > 0)

        def analyser_disque() -> _StepOutcome:
            import psutil
            usage = psutil.disk_usage(".")
            return _StepOutcome(f"Libre: {usage.free // (1024**3)} Go ({usage.percent}% utilisé)")

        steps = [("purgers_pyc", purger_pyc), ("analyser_disque", analyser_disque)]

    elif identifiant == "sauvegarde_securisee":
        snapshot_path = None

        def creer_snapshot() -> _StepOutcome:
            from syncsphere.tools import creer_snapshot_systeme_capability
            from greatos_contracts import CapabilityStatus

            name = f"workflow_{uuid4().hex}.gos"
            result = creer_snapshot_systeme_capability(name, chiffrer=True)
            if result.status != CapabilityStatus.SUCCESS:
                effects = ([{"etape": "creer_snapshot", "details": result.message}] if result.effect_status == "partial" else [])
                raise _StepFailure(result.message, effects)
            nonlocal snapshot_path
            from pathlib import Path
            snapshot_path = Path(result.data["path"])
            return _StepOutcome(result.message, compensation=result.compensator, effect_applied=True)

        def verifier_snapshot() -> _StepOutcome:
            from syncsphere.snapshot import snapshot_manager
            if snapshot_path is None:
                raise RuntimeError("Le snapshot à vérifier n'est pas disponible.")
            details = snapshot_manager.verifier_integrite(snapshot_path, exiger_chiffrement=True)
            return _StepOutcome(f"Intégrité AES-GCM valide; {len(details['fichiers_verifies'])} fichiers vérifiés")

        steps = [("creer_snapshot", creer_snapshot), ("verifier_integrite", verifier_snapshot)]

    else:  # synthese_projet: lecture seule
        def lire_journal() -> _StepOutcome:
            from core_intellect.system_introspection import consulter_historique_projet
            sessions = consulter_historique_projet(nombre=3)
            return _StepOutcome(f"{len(sessions)} sessions chargées")

        def lire_objectifs() -> _StepOutcome:
            from progress_tracker.tools import stats_objectifs_tool
            return _StepOutcome(str(stats_objectifs_tool()))

        steps = [("lire_journal_sessions", lire_journal), ("analyser_objectifs", lire_objectifs)]

    result = _executer_etapes(steps)
    result["workflow"] = WORKFLOWS_CATALOGUE[identifiant]["nom"]
    result["duree_secondes"] = round(time.perf_counter() - start, 2)
    return result
