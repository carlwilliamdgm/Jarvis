"""System Introspection - Outils d'introspection déterministe de GreatOS pour Jarvis.

Permet à Jarvis de connaître sa propre maison, son architecture et l'historique
du projet à la demande, sans surcharger son prompt de base.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

RACINE_PROJET = Path(__file__).resolve().parent.parent

# Cartographie officielle des modules GreatOS (source de vérité CDC)
CREATEUR_GREATOS = "Carl-William DJEGUEMA (Étudiant en Génie Logiciel à l'IAI-Togo)"

ARCHITECTURE_GREATOS = {
    "greatos": {
        "nom": "GreatOS Core Launcher",
        "createur": CREATEUR_GREATOS,
        "role": "Point d'entrée principal et orchestrateur des services résidents",
        "fichiers_cles": ["greatos.py", "greatos_service.py", "jarvis_hidden.ps1"],
    },
    "core_intellect": {
        "nom": "Core Intellect / Jarvis (Le Cerveau Orchestrateur)",
        "role": "Chef d'orchestre central de GreatOS : décision, raisonnement déterministe, routage d'intentions et supervision des modules",
        "fichiers_cles": ["intellect.py", "intent_router.py", "tool_registry.py", "personality.py", "system_introspection.py"],
    },
    "context_engine": {
        "nom": "Context Engine (La Conscience)",
        "role": "Hooks Win32 réactifs sans polling, veille proactive, monitoring système et vision",
        "fichiers_cles": ["os_hooks.py", "desktop_awareness.py", "system_monitor.py", "proactive_daemon.py"],
    },
    "taskflow": {
        "nom": "TaskFlow (Les Bras)",
        "role": "Automatisation du navigateur Playwright, UI automation, exécution de commandes et outils",
        "fichiers_cles": ["tools.py", "browser_session.py", "scheduler.py"],
    },
    "datashield": {
        "nom": "DataShield (Le Bouclier)",
        "role": "Chiffrement militaire AES-256-GCM, contrôle DEFCON, politique de sécurité et trust matrix",
        "fichiers_cles": ["crypto.py", "policy.py", "threat_analyzer.py", "env_loader.py"],
    },
    "interface_morphique": {
        "nom": "Interface Morphique (Le Visage)",
        "role": "8 layouts contextuels réactifs, serveur FastAPI, interface web SSE et HUD vocal",
        "fichiers_cles": ["context_switcher.py", "server.py", "voice_overlay.py", "web/index.html"],
    },
    "progress_tracker": {
        "nom": "Progress Tracker (Le Compas)",
        "role": "Suivi des objectifs, métriques de complétion et indicateurs de progression",
        "fichiers_cles": ["tracker.py", "metrics.py"],
    },
    "syncsphere": {
        "nom": "SyncSphere (Le Réseau)",
        "role": "Synchronisation chiffrée multi-appareils, snapshots et maillage Tailscale",
        "fichiers_cles": ["sync_engine.py", "crypto.py"],
    },
}


def consulter_etat_maison(domaine: str = "tout") -> Dict[str, Any]:
    """Retourne l'état en direct de GreatOS et de l'environnement Windows.

    Args:
        domaine: 'contexte' (fenêtre active/plein écran), 'morphic' (layout actuel),
                 'systeme' (CPU/RAM/disque), 'securite' (chiffrement), ou 'tout'.
    """
    etat: Dict[str, Any] = {}

    # 1. Contexte OS actif (Hooks réactifs Win32)
    if domaine in ("contexte", "tout"):
        try:
            from context_engine.os_hooks import get_os_hook_manager
            manager = get_os_hook_manager()
            ctx = manager.get_current_context()
            etat["contexte_os"] = {
                "application": ctx.get("application", "Inconnue"),
                "titre_fenetre": ctx.get("titre", ""),
                "processus": ctx.get("processus", ""),
                "pid": ctx.get("pid"),
                "plein_ecran": ctx.get("plein_ecran", False),
                "derniere_activite": ctx.get("timestamp"),
            }
        except Exception as e:
            etat["contexte_os"] = {"erreur": str(e)}

    # 2. Layout morphique actuel
    if domaine in ("morphic", "tout"):
        try:
            from interface_morphique.context_switcher import get_morphic_engine
            engine = get_morphic_engine()
            layout = engine.get_current_layout()
            etat["layout_morphique"] = {
                "layout_actuel": layout.value if hasattr(layout, "value") else str(layout),
            }
        except Exception as e:
            etat["layout_morphique"] = {"erreur": str(e)}

    # 3. Métriques système
    if domaine in ("systeme", "tout"):
        try:
            from context_engine.system_monitor import obtenir_etat_systeme_complet
            sys_info = obtenir_etat_systeme_complet()
            partitions = sys_info.get("disque", {}).get("partitions", [])
            premier_disque = partitions[0] if partitions else {}
            etat["systeme"] = {
                "cpu_percent": sys_info.get("cpu", {}).get("utilisation"),
                "ram_percent": sys_info.get("memoire", {}).get("pourcentage"),
                "disque_libre_gb": round(premier_disque.get("libre", 0) / (1024**3), 1) if premier_disque else None,
            }
        except Exception as e:
            etat["systeme"] = {"erreur": str(e)}

    # 4. Sécurité & Chiffrement
    if domaine in ("securite", "tout"):
        try:
            from datashield.crypto import crypto_engine
            etat["securite"] = {
                "chiffrement_actif": crypto_engine.is_enabled,
                "algorithme": "AES-256-GCM (PBKDF2-HMAC-SHA256)",
            }
        except Exception as e:
            etat["securite"] = {"erreur": str(e)}

    return etat


def inspecter_architecture_greatos(module: Optional[str] = None) -> Dict[str, Any]:
    """Retourne la cartographie officielle des modules de GreatOS et leur rôle.

    Args:
        module: Nom du module (ex: 'core_intellect', 'taskflow', 'datashield') ou None pour tous.
    """
    if module and module in ARCHITECTURE_GREATOS:
        return {module: ARCHITECTURE_GREATOS[module]}
    return ARCHITECTURE_GREATOS


def consulter_historique_projet(nombre: int = 3) -> List[Dict[str, Any]]:
    """Retourne les dernières sessions de travail et décisions enregistrées dans le projet.

    Source de vérité : learning/agent_sessions.jsonl (AGENTS.md).
    """
    fichier_journal = RACINE_PROJET / "learning" / "agent_sessions.jsonl"
    if not fichier_journal.exists():
        return []

    lignes = []
    try:
        with open(fichier_journal, "r", encoding="utf-8") as f:
            for ligne in f:
                texte = ligne.strip()
                if texte:
                    try:
                        lignes.append(json.loads(texte))
                    except Exception:
                        pass
    except Exception:
        return []

    # Retourner les 'nombre' plus récentes
    sessions_recentes = lignes[-nombre:]
    resultats = []
    for s in reversed(sessions_recentes):
        resultats.append({
            "timestamp": s.get("timestamp"),
            "agent": s.get("agent"),
            "statut": s.get("status"),
            "resume": s.get("summary"),
            "changements": s.get("changes"),
            "apprentissages": s.get("learnings"),
        })
    return resultats
