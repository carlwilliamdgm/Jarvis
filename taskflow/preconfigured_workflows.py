"""TaskFlow - Workflows Préconfigurés (CDC GreatOS Module 4.4).

Fournit des scénarios d'automatisation clé en main pour l'utilisateur :
1. session_dev : Prépare la session de travail et d'ingénierie logicielle
2. nettoyage_systeme : Purge des fichiers temporaires et caches résiduels
3. sauvegarde_securisee : Snapshot local chiffré via SyncSphere et DataShield
4. synthese_projet : Revue des sessions d'apprentissage et statut des objectifs
"""

from __future__ import annotations

import time
from typing import Any, Dict, List


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
        "description": "Extrait les dernières sessions enregistrées et les jalons franchis.",
        "etapes": ["lire_journal_sessions", "analyser_objectifs"],
    },
}


def lister_workflows_preconfigures() -> Dict[str, Any]:
    """Retourne la liste des workflows disponibles avec leurs étapes."""
    return WORKFLOWS_CATALOGUE


def executer_workflow_preconfigure(identifiant: str) -> Dict[str, Any]:
    """Exécute un workflow préconfiguré de manière déterministe et traçable."""
    if identifiant not in WORKFLOWS_CATALOGUE:
        return {
            "succes": False,
            "erreur": f"Workflow '{identifiant}' inconnu. Disponibles : {list(WORKFLOWS_CATALOGUE.keys())}",
        }

    wf = WORKFLOWS_CATALOGUE[identifiant]
    resultats_etapes: List[Dict[str, Any]] = []
    t_debut = time.time()

    if identifiant == "session_dev":
        # 1. Vérification Git
        try:
            import subprocess
            proc = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=3)
            resultats_etapes.append({"etape": "verifier_git", "statut": "ok", "details": f"{len(proc.stdout.splitlines())} fichiers modifiés"})
        except Exception as e:
            resultats_etapes.append({"etape": "verifier_git", "statut": "erreur", "details": str(e)})

        # 2. Contexte Machine
        try:
            from context_engine.four_dimensions import capturer_contexte_quadridimensionnel
            ctx = capturer_contexte_quadridimensionnel()
            resultats_etapes.append({"etape": "inspecter_ressources", "statut": "ok", "details": f"CPU: {ctx.operationnel.cpu_percent}%, RAM: {ctx.operationnel.ram_percent}%"})
        except Exception as e:
            resultats_etapes.append({"etape": "inspecter_ressources", "statut": "erreur", "details": str(e)})

        # 3. Notification Morphique Focus
        try:
            from interface_morphique.context_switcher import get_morphic_engine
            get_morphic_engine().notifier_evenement("dev_session_started", {})
            resultats_etapes.append({"etape": "activer_focus", "statut": "ok", "details": "Signal focus émis"})
        except Exception as e:
            resultats_etapes.append({"etape": "activer_focus", "statut": "erreur", "details": str(e)})

    elif identifiant == "nettoyage_systeme":
        # Purge .pyc
        nb_pyc = 0
        try:
            from pathlib import Path
            for p in Path(".").rglob("*.pyc"):
                try:
                    p.unlink()
                    nb_pyc += 1
                except Exception:
                    pass
            resultats_etapes.append({"etape": "purgers_pyc", "statut": "ok", "details": f"{nb_pyc} fichiers .pyc purgés"})
        except Exception as e:
            resultats_etapes.append({"etape": "purgers_pyc", "statut": "erreur", "details": str(e)})

        # Espace disque
        try:
            import psutil
            du = psutil.disk_usage(".")
            resultats_etapes.append({"etape": "analyser_disque", "statut": "ok", "details": f"Libre: {du.free // (1024**3)} Go ({du.percent}% utilisé)"})
        except Exception as e:
            resultats_etapes.append({"etape": "analyser_disque", "statut": "erreur", "details": str(e)})

    elif identifiant == "sauvegarde_securisee":
        try:
            from syncsphere.tools import creer_snapshot_systeme_tool
            res = creer_snapshot_systeme_tool(description="Workflow automatique TaskFlow")
            resultats_etapes.append({"etape": "creer_snapshot", "statut": "ok", "details": str(res)[:100]})
        except Exception as e:
            resultats_etapes.append({"etape": "creer_snapshot", "statut": "erreur", "details": str(e)})

    elif identifiant == "synthese_projet":
        try:
            from core_intellect.system_introspection import consulter_historique_projet
            sessions = consulter_historique_projet(nombre=3)
            resultats_etapes.append({"etape": "lire_journal_sessions", "statut": "ok", "details": f"{len(sessions)} sessions chargées"})
        except Exception as e:
            resultats_etapes.append({"etape": "lire_journal_sessions", "statut": "erreur", "details": str(e)})

    duree = round(time.time() - t_debut, 2)
    return {
        "workflow": wf["nom"],
        "succes": all(e.get("statut") == "ok" for e in resultats_etapes),
        "duree_secondes": duree,
        "etapes": resultats_etapes,
    }
