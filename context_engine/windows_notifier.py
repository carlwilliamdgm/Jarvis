"""Système de notifications Toast Windows natives pour GreatOS / J.A.R.V.I.S.

Permet à GreatOS d'interagir proactivement avec l'utilisateur via des notifications
Windows 10/11 sans dépendance externe bloquante.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import threading
from typing import Any, Optional

LOGGER = logging.getLogger("context_engine.notifier")

_SCRIPT_TOAST = Path(__file__).resolve().parents[1] / "scripts" / "show_toast.ps1"
_LISTENER_THREAD: Optional[threading.Thread] = None
_STOP_EVENT = threading.Event()


def envoyer_toast(titre: str, message: str) -> bool:
    """Envoie une notification Toast Windows en arrière-plan de manière asynchrone."""
    if os.name != "nt":
        LOGGER.info("[Toast non-Windows] %s : %s", titre, message)
        return True

    if not _SCRIPT_TOAST.is_file():
        LOGGER.warning("Script show_toast.ps1 introuvable: %s", _SCRIPT_TOAST)
        return False

    def _execute():
        try:
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(_SCRIPT_TOAST),
                "-Title", str(titre),
                "-Message", str(message),
            ]
            flags = 0x08000000  # CREATE_NO_WINDOW
            subprocess.run(
                cmd,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            LOGGER.exception("Échec de l'envoi du toast Windows")

    threading.Thread(target=_execute, name="toast-worker", daemon=True).start()
    return True


def _ecouteur_evenements_notifier(event_bus: Any) -> None:
    """Boucle d'écoute des événements de l'EventBus pour déclencher les notifications."""
    event_queue = event_bus.subscribe()
    try:
        while not _STOP_EVENT.is_set():
            try:
                event = event_queue.get(timeout=1.0)
            except Exception:
                continue

            event_type = event.get("type", "")
            data = event.get("data", {})

            if event_type == "reminder":
                msg = data.get("message", "Rappel prévu atteint.")
                envoyer_toast("J.A.R.V.I.S. | Rappel", msg)

            elif event_type == "alerte_proactive":
                desc = data.get("description") or data.get("message") or "Anomalie système détectée."
                envoyer_toast("J.A.R.V.I.S. | Veille Proactive", desc)

            elif event_type == "plan_completed":
                goal = data.get("goal", "Objectif")
                envoyer_toast("J.A.R.V.I.S. | Plan Terminé", f"Exécution terminée : {goal}")
    finally:
        event_bus.unsubscribe(event_queue)


def demarrer_notifier_proactif(event_bus: Any) -> threading.Thread:
    """Démarre le pont entre l'EventBus et les notifications Toast Windows."""
    global _LISTENER_THREAD
    _STOP_EVENT.clear()
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        return _LISTENER_THREAD
    _LISTENER_THREAD = threading.Thread(
        target=_ecouteur_evenements_notifier,
        args=(event_bus,),
        name="greatos-toast-bridge",
        daemon=True,
    )
    _LISTENER_THREAD.start()
    return _LISTENER_THREAD


def arreter_notifier_proactif() -> None:
    """Arrête le pont des notifications Toast."""
    _STOP_EVENT.set()
