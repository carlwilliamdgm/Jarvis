from collections import OrderedDict, deque
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import ssl
import subprocess
import sys
import struct
import threading
import time
from typing import Dict, List
from urllib.parse import quote, urlsplit
from uuid import uuid4

"""
Jarvis API Server - State Consistency Guarantees
=================================================

This API provides a REST interface to Jarvis with the following state consistency guarantees:

Execution Model:
- User interactions (CLI, API, voice) are serialized by INTERACTION_LOCK (process-level lock in jarvis.py)
- Only one user interaction can execute at a time per process
- This prevents race conditions on shared in-memory state during user interactions
- The autonomous agent runs independently and does NOT acquire INTERACTION_LOCK
- This allows continuous system observation without blocking user interactions

State Persistence:
- Tools may persist data (e.g., memory.json) or modify the system during execution
- memory.json writes are serialized by _MEMORY_LOCK in core/memory.py to prevent corruption
- Other external effects (file system, shell commands, external APIs) are NOT globally transactional
- These external effects are applied immediately with no global rollback mechanism

Error Handling:
- On exception: a clean error response is returned (HTTP 500 or SSE error event)
- In-memory state (historique, memoire, global flags) may be partially updated
- The conversation history remains coherent and usable after errors
- Global flags (mode_action_force, ATTENTE_DETAILS_STARK, etc.) have predictable post-error behavior

Why No Global Rollback?
- Tools can write to disk, execute shell commands, make network calls, etc.
- These external effects cannot be reliably undone after they occur
- Workflow steps may declare safe compensations; only those compensations are run in reverse order
- Effects without a declared compensation remain applied and are reported explicitly
- Pretending every external effect can be reversed would be misleading and dangerous

Concurrency:
- User interactions are serialized per INTERACTION_LOCK
- The autonomous agent runs independently for continuous system monitoring
- Persistent writes (memory.json, file operations) are serialized by PERSISTENCE_LOCK
- This ensures data consistency while allowing autonomous observation
"""

import logging
import secrets
import psutil
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger("jarvis.server")

# Force UTF-8 encoding to avoid charmap errors on Windows
if sys.stdout is not None and getattr(sys.stdout, 'encoding', None) != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr is not None and getattr(sys.stderr, 'encoding', None) != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from core_intellect.llm_client import get_llm_client
from jarvis.agent import (
    arreter_daemon_proactif,
    demarrer_agent_autonome,
    demarrer_daemon_proactif,
    event_bus,
    executer_interaction_utilisateur,
    initialiser,
)
from context_engine.consolidation_scheduler import ConsolidationScheduler
from context_engine.system_monitor import obtenir_infos_tailscale
from context_engine.os_hooks import demarrer_os_hooks, arreter_os_hooks
from interface_morphique.context_switcher import get_morphic_engine
from interface_morphique.voice_overlay import demarrer_overlay_vocal, arreter_overlay_vocal
from jarvis.voice_input import demarrer_ecoute_vocale, arreter_ecoute_vocale, get_voice_input_status
from jarvis.clap_input import demarrer_ecoute_clap, arreter_ecoute_clap
from core_intellect.prompt import construire_prompt_action
from datashield.autodestruct import schedule_autodestruction
from datashield.confirmations import (
    StreamingConfirmationHandler,
    confirmation_manager,
    use_confirmation_handler,
)

from contextlib import asynccontextmanager


_RUNTIME_START_LOCK = threading.Lock()
_RUNTIME_STARTED = False
WINDOWS_SESSION_LOCKED = threading.Event()
_ACTIVE_PROFILE_WORKERS: set[threading.Thread] = set()
_ACTIVE_PROFILE_WORKERS_LOCK = threading.Lock()
_PROFILE_LOCK_TEARDOWN_LOCK = threading.Lock()


def _windows_session_lifecycle_enabled() -> bool:
    return os.name == "nt"


def _start_runtime_services(app: FastAPI, expected_generation: int | None = None) -> None:
    """Start profile-backed workers once DataShield has been unlocked."""
    global agent, agent_stop_event, memoire, historique, _RUNTIME_STARTED, _agent_thread
    from datashield.crypto import crypto_engine
    from datashield.profile_gate import profile_execution_gate
    if WINDOWS_SESSION_LOCKED.is_set() or not crypto_engine.is_enabled:
        return
    if _profile_workers_pending(app):
        raise RuntimeError("Un worker de l’ancien profil termine encore son arrêt sécurisé.")
    with _RUNTIME_START_LOCK:
        if WINDOWS_SESSION_LOCKED.is_set() or not crypto_engine.is_enabled or _RUNTIME_STARTED:
            return
        try:
            if _agent_thread is not None and _agent_thread.is_alive():
                raise RuntimeError("Un ancien agent GreatOS n’a pas terminé son arrêt sécurisé.")
            memoire = initialiser()
            llm_client = get_llm_client()
            from rich.console import Console

            console = Console()
            agent, agent_stop_event, _agent_thread = demarrer_agent_autonome(memoire, console)

            prompt = construire_prompt_action(memoire)
            historique = [{"role": "system", "content": prompt}]

            # Attacher l'état global et les services à app.state
            app.state.memoire = memoire
            app.state.llm_client = llm_client
            app.state.agent = agent
            app.state.agent_stop_event = agent_stop_event

            # Démarrer l'overlay visuel vocal
            try:
                demarrer_overlay_vocal()
            except Exception as e:
                logger.warning("Could not start voice overlay: %s", e)

            # Suivre le défaut de l'hôte même si aucun micro n'est connecté au boot.
            _voice_disabled = os.environ.get("GREATOS_DISABLE_VOICE", "").lower() in ("1", "true", "yes")
            _voice_status = get_voice_input_status()
            _mic_available = bool(_voice_status.get("audio", {}).get("default_input", {}).get("available"))
            try:
                from jarvis.voice_state import _set_voice_audio_input
                _set_voice_audio_input({
                    "available": _mic_available,
                    "device": _voice_status.get("audio", {}).get("default_input", {}).get("name"),
                    "reason": _voice_status.get("reason"),
                })
            except Exception:
                logger.debug("Could not publish host microphone state to HUD", exc_info=True)

            if not _voice_disabled:
                # Démarrer les écouteurs même sans micro présent : le moteur
                # réessaie et suivra un défaut Windows défini plus tard.
                try:
                    demarrer_ecoute_vocale()
                    logger.info("Voice listener started successfully")
                except Exception as e:
                    logger.warning("Could not start voice listener: %s", e)

                # Démarrer l'écoute double-clap
                try:
                    demarrer_ecoute_clap()
                    logger.info("Double-clap listener started successfully")
                except Exception as e:
                    logger.warning("Could not start double-clap listener: %s", e)
            elif _voice_disabled:
                logger.info("Écoute vocale ignorée au démarrage (désactivée via GREATOS_DISABLE_VOICE).")
            if not _mic_available and not _voice_disabled:
                logger.warning("Aucun micro par défaut Windows disponible; les écouteurs restent en attente du choix de l'hôte.")

            # Démarrer l'overlay visuel de navigation
            try:
                from interface_morphique.browser_overlay import start_browser_overlay
                start_browser_overlay()
                logger.info("Browser overlay started successfully")
            except Exception as e:
                logger.warning("Could not start browser overlay: %s", e)

            # Démarrer l'interception réactive des événements OS
            try:
                demarrer_os_hooks()
                logger.info("OS hooks started successfully")
            except Exception as e:
                logger.warning("Could not start OS hooks: %s", e)

            # Démarrer le moteur de bascule contextuelle Interface Morphique
            try:
                get_morphic_engine().demarrer()
                logger.info("Morphic context engine started successfully")
            except Exception as e:
                logger.warning("Could not start morphic engine: %s", e)

            logger.info("Jarvis API server started successfully")
            # Démarrer le thread de sampling CPU non-bloquant pour /jarvis/status
            _demarrer_cpu_sampler()
            proactive_daemon = demarrer_daemon_proactif(event_bus)
            consolidation_scheduler = ConsolidationScheduler()
            consolidation_scheduler.start()
            app.state.proactive_daemon = proactive_daemon
            app.state.consolidation_scheduler = consolidation_scheduler

            # Démarrer le scheduler taskflow (rappels + automatisations)
            try:
                taskflow_scheduler = _demarrer_taskflow_scheduler()
                app.state.taskflow_scheduler = taskflow_scheduler
                logger.info("Taskflow scheduler (rappels/automatisations) démarré")
            except Exception as e:
                logger.warning("Could not start taskflow scheduler: %s", e)

            # Démarrer le pont de notifications Toast Windows natives (proactivité)
            try:
                from context_engine.windows_notifier import demarrer_notifier_proactif
                demarrer_notifier_proactif(event_bus)
                logger.info("Windows Toast notifier bridge started successfully")
            except Exception as e:
                logger.warning("Could not start Windows toast notifier bridge: %s", e)

            # Démarrer l'icône de zone de notification (System Tray) Windows
            try:
                from interface_morphique.tray_icon import demarrer_tray_icon
                demarrer_tray_icon(web_url="http://127.0.0.1:8000/web/")
                logger.info("System Tray Icon started successfully")
            except Exception as e:
                logger.warning("Could not start System Tray Icon: %s", e)
            if expected_generation is None:
                event_bus.set_profile_locked(False)
                profile_execution_gate.set_locked(False)
            else:
                from datashield.windows_session import input_desktop_is_unlocked
                if (
                    WINDOWS_SESSION_LOCKED.is_set()
                    or profile_execution_gate.generation != expected_generation
                    or not input_desktop_is_unlocked()
                    or not profile_execution_gate.unlock_if_generation(expected_generation)
                ):
                    raise RuntimeError("Le bureau Windows a changé pendant la reprise sécurisée.")
                event_bus.set_profile_locked(False)
        except Exception as e:
            logger.error("Error initializing agent: %s", e)
            raise
        _RUNTIME_STARTED = True
        app.state.runtime_services_started = True


def _stop_profile_runtime(app: FastAPI, reason: str) -> None:
    """Stop profile workers, invalidate credentials, purge references, then lock the key."""
    global agent, agent_stop_event, memoire, historique, _RUNTIME_STARTED, _agent_thread
    from datashield.crypto import crypto_engine

    # The state gate is raised by the caller before this routine, so no new API
    # request or SSE consumer can enter while workers are being stopped.
    crypto_engine.lock()
    with _REMOTE_AUTH_LOCK:
        _REMOTE_AUTH_SESSIONS.clear()
        _REMOTE_TOTP_FAILURES.clear()
    confirmation_manager.cancel_all()

    with _RUNTIME_START_LOCK:
        if agent_stop_event is not None:
            agent_stop_event.set()
        scheduler = getattr(app.state, "consolidation_scheduler", None)
        scheduler_stopped = scheduler is None
        if scheduler is not None:
            try:
                scheduler.arreter()
                scheduler.join(timeout=3.0)
                scheduler_stopped = not scheduler.is_alive()
                if not scheduler_stopped:
                    logger.error("Consolidation worker remains alive after Windows session lock")
            except Exception:
                logger.exception("Unable to stop consolidation during Windows session lock")
        try:
            arreter_daemon_proactif()
        except Exception:
            logger.exception("Unable to stop proactive daemon during Windows session lock")
        try:
            _arreter_taskflow_scheduler()
            tf_sched = getattr(app.state, "taskflow_scheduler", None)
            if tf_sched is not None:
                tf_sched.join(timeout=2.0)
                app.state.taskflow_scheduler = None
        except Exception:
            logger.exception("Unable to stop taskflow scheduler during Windows session lock")
        try:
            from context_engine.windows_notifier import arreter_notifier_proactif
            arreter_notifier_proactif()
        except Exception:
            logger.exception("Unable to stop toast notifier bridge during Windows session lock")
        try:
            from interface_morphique.tray_icon import arreter_tray_icon
            arreter_tray_icon()
        except Exception:
            logger.exception("Unable to stop tray icon during Windows session lock")
        for stop in (arreter_overlay_vocal, arreter_ecoute_vocale, arreter_ecoute_clap,
                     arreter_os_hooks):
            try:
                stop()
            except Exception:
                logger.exception("Unable to stop a profile worker during Windows session lock")
        try:
            from interface_morphique.browser_overlay import stop_browser_overlay
            stop_browser_overlay()
        except Exception:
            logger.exception("Unable to stop browser overlay during Windows session lock")
        try:
            get_morphic_engine().arreter()
        except Exception:
            logger.exception("Unable to stop morphic engine during Windows session lock")
        agent_thread = _agent_thread
        if agent_thread is not None and agent_thread.is_alive():
            agent_thread.join(timeout=3.0)
            if agent_thread.is_alive():
                logger.error("Autonomous profile agent is still stopping after Windows session lock")

        try:
            event_bus.clear_sensitive_state()
        except Exception:
            logger.exception("Unable to clear queued profile events during Windows session lock")
        signal_queue.clear()
        alerts_queue.clear()
        agent = None
        agent_stop_event = None
        memoire = None
        historique = None
        _RUNTIME_STARTED = False
        if agent_thread is None or not agent_thread.is_alive():
            _agent_thread = None
        app.state.memoire = None
        app.state.agent = None
        app.state.agent_stop_event = None
        app.state.llm_client = None
        app.state.runtime_services_started = False
        if scheduler is not None and scheduler_stopped:
            app.state.consolidation_scheduler = None
    logger.info("DataShield profile runtime locked after Windows session event: %s", reason)


def _profile_workers_pending(app: FastAPI) -> bool:
    """Return true while any profile-bound worker from the previous session lives."""
    from datashield.profile_gate import profile_execution_gate
    if profile_execution_gate.active_count:
        return True
    agent_thread = _agent_thread
    if agent_thread is not None and agent_thread.is_alive():
        return True
    workers = []
    scheduler = getattr(app.state, "consolidation_scheduler", None)
    if scheduler is not None:
        workers.append(scheduler)
    try:
        from jarvis import agent as agent_module
        proactive = getattr(agent_module, "_proactive_daemon", None)
        if proactive is not None:
            workers.append(proactive)
    except Exception:
        return True
    try:
        from jarvis import voice_input, clap_input
        workers.extend((getattr(voice_input, "_LISTENER_THREAD", None),
                        getattr(clap_input, "_LISTENER_THREAD", None)))
    except Exception:
        return True
    try:
        from context_engine import os_hooks
        manager = getattr(os_hooks, "_os_hook_manager", None)
        workers.append(getattr(manager, "_hook_thread", None) if manager else None)
    except Exception:
        return True
    try:
        from interface_morphique import context_switcher
        engine = getattr(context_switcher, "_morphic_engine", None)
        workers.append(getattr(engine, "_listener_thread", None) if engine else None)
    except Exception:
        return True
    try:
        from interface_morphique import browser_overlay
        overlay = getattr(browser_overlay, "_overlay_instance", None)
        workers.append(getattr(overlay, "thread", None) if overlay else None)
    except Exception:
        return True
    try:
        from interface_morphique import voice_overlay
        process = getattr(voice_overlay, "_overlay_process", None)
        if process is not None and process.poll() is None:
            return True
    except Exception:
        return True
    return any(worker is not None and worker.is_alive() for worker in workers)


def _stop_profile_runtime_after_active_steps(
    app: FastAPI,
    reason: str,
    lock_generation: int,
) -> threading.Thread | None:
    """Defer key/runtime teardown until actions admitted before lock have drained."""
    from datashield.profile_gate import profile_execution_gate

    with _PROFILE_LOCK_TEARDOWN_LOCK:
        if getattr(app.state, "windows_session_teardown_generation", None) == lock_generation:
            return getattr(app.state, "windows_session_lock_worker", None)
        app.state.windows_session_teardown_generation = lock_generation
        app.state.windows_session_teardown_complete = False

    def finish_lock() -> None:
        profile_execution_gate.wait_for_action_steps()
        if (
            profile_execution_gate.generation == lock_generation
            and WINDOWS_SESSION_LOCKED.is_set()
        ):
            with _PROFILE_LOCK_TEARDOWN_LOCK:
                if getattr(app.state, "windows_session_teardown_complete", False):
                    return
                app.state.windows_session_teardown_complete = True
            _stop_profile_runtime(app, reason)

    if not profile_execution_gate.active_action_steps:
        finish_lock()
        return None
    worker = threading.Thread(
        target=finish_lock,
        name="greatos-lock-after-active-step",
        daemon=True,
    )
    with _PROFILE_LOCK_TEARDOWN_LOCK:
        app.state.windows_session_lock_worker = worker
    worker.start()
    return worker


def _handle_windows_session_lock(app: FastAPI, reason: str) -> None:
    from datashield.profile_gate import profile_execution_gate
    # Close admission atomically before publishing the broader HTTP session gate.
    profile_execution_gate.set_locked(True)
    WINDOWS_SESSION_LOCKED.set()
    # Annuler immédiatement toute confirmation interactive pendante pour ne pas
    # retenir les action_steps en cours jusqu'au timeout (ex. 120s).
    confirmation_manager.cancel_all()
    # Stop any spoken response that could still contain profile data. Edge TTS
    # uses PlaySound's process-wide Windows output and needs an explicit purge.
    try:
        from jarvis.voice_output import arreter_toutes_sorties_tts
        arreter_toutes_sorties_tts()
    except Exception:
        logger.debug("Unable to purge TTS output during Windows session lock", exc_info=True)
    try:
        from jarvis.voice_state import VoiceState, _set_voice_state
        _set_voice_state(VoiceState.IDLE)
    except Exception:
        logger.debug("Unable to reset voice state during Windows session lock", exc_info=True)
    event_bus.set_profile_locked(True)
    lock_generation = profile_execution_gate.generation
    _stop_profile_runtime_after_active_steps(app, reason, lock_generation)



def _handle_windows_session_unlock(app: FastAPI, expected_generation: int | None = None) -> None:
    from datashield.crypto import crypto_engine
    from datashield.profile_gate import profile_execution_gate
    from jarvis.agent import INTERACTION_LOCK

    # A Python thread cannot be safely killed while it is inside an external
    # capability. Keep the profile gated until its current interaction reaches
    # a safe boundary and releases the serialization lock.
    with _ACTIVE_PROFILE_WORKERS_LOCK:
        active_profile_worker = any(thread.is_alive() for thread in _ACTIVE_PROFILE_WORKERS)
    generation = profile_execution_gate.generation if expected_generation is None else expected_generation
    if generation != profile_execution_gate.generation:
        raise RuntimeError("La transition Windows a invalidé cette demande de reprise.")
    if INTERACTION_LOCK.locked() or active_profile_worker or _profile_workers_pending(app):
        raise RuntimeError("Une interaction GreatOS est encore en cours d’arrêt.")

    if not __import__("datashield.windows_session", fromlist=["input_desktop_is_unlocked"]).input_desktop_is_unlocked():
        raise RuntimeError("Le bureau d’entrée Windows n’est pas déverrouillé.")

    if not crypto_engine.is_enabled and not crypto_engine.is_hello_wrapped:
        try:
            if crypto_engine.dpapi_recovery_available:
                crypto_engine.unlock_from_key_store()
        except Exception as exc:
            logger.warning("Current Windows account could not reopen the DPAPI profile: %s", type(exc).__name__)
    WINDOWS_SESSION_LOCKED.clear()
    if crypto_engine.is_enabled:
        try:
            _start_runtime_services(app, expected_generation=generation)
        except Exception:
            WINDOWS_SESSION_LOCKED.set()
            event_bus.set_profile_locked(True)
            crypto_engine.lock()
            logger.exception("GreatOS failed to resume after Windows session unlock; profile remains locked")
            raise


def _schedule_windows_session_unlock(app: FastAPI) -> None:
    """Keep the WTS message pump responsive while profile services restart."""
    from datashield.profile_gate import profile_execution_gate
    monitor = getattr(app.state, "windows_session_monitor", None)
    generation = profile_execution_gate.generation

    def resume() -> None:
        try:
            _handle_windows_session_unlock(app, expected_generation=generation)
        except Exception:
            logger.exception("Asynchronous GreatOS resume failed; session remains locked")
            _handle_windows_session_lock(app, "unlock_resume_failed")
            if monitor is not None:
                monitor.request_reconcile()

    worker = threading.Thread(target=resume, name="greatos-session-resume", daemon=True)
    app.state.windows_session_resume_worker = worker
    worker.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bind GreatOS profile availability to the current interactive Windows session."""
    from datashield.crypto import crypto_engine
    from datashield.profile_gate import profile_execution_gate
    app.state.runtime_services_started = False
    if _windows_session_lifecycle_enabled():
        # Fail closed until the interactive input desktop is positively confirmed.
        profile_execution_gate.set_locked(True)
        WINDOWS_SESSION_LOCKED.set()
        event_bus.clear_sensitive_state()
        from datashield.windows_session import WindowsSessionMonitor
        monitor = WindowsSessionMonitor(
            on_locked=lambda reason: _handle_windows_session_lock(app, reason),
            on_unlocked=lambda: _schedule_windows_session_unlock(app),
        )
        app.state.windows_session_monitor = monitor
        try:
            monitor.start()
        except Exception:
            WINDOWS_SESSION_LOCKED.set()
            profile_execution_gate.set_locked(True)
            crypto_engine.lock()
            logger.exception("Windows session monitor unavailable; GreatOS stays locked")
    elif crypto_engine.is_enabled:
        _start_runtime_services(app)
    else:
        app.state.runtime_services_started = False
        logger.info("GreatOS démarre verrouillé; le profil chiffré attend un déverrouillage autorisé.")

    yield

    _handle_windows_session_lock(app, "process_shutdown")
    monitor = getattr(app.state, "windows_session_monitor", None)
    if monitor is not None:
        try:
            monitor.stop()
        except Exception:
            logger.exception("Unable to stop Windows session monitor during application shutdown")

    if not getattr(app.state, "runtime_services_started", False):
        return
    if agent_stop_event is not None:
        agent_stop_event.set()
    arreter_daemon_proactif()
    try:
        _arreter_taskflow_scheduler()
    except Exception:
        logger.exception("Unable to stop taskflow scheduler during application shutdown")
    try:
        from context_engine.windows_notifier import arreter_notifier_proactif
        arreter_notifier_proactif()
    except Exception:
        logger.exception("Unable to stop toast notifier bridge during application shutdown")
    try:
        from interface_morphique.tray_icon import arreter_tray_icon
        arreter_tray_icon()
    except Exception:
        logger.exception("Unable to stop tray icon during application shutdown")
    scheduler = getattr(app.state, "consolidation_scheduler", None)
    if scheduler is not None:
        scheduler.arreter()
        scheduler.join(timeout=2.0)
    # Arrêter l'overlay visuel vocal
    arreter_overlay_vocal()
    # Arrêter l'écoute vocale
    try:
        arreter_ecoute_vocale()
        logger.info("Voice listener stopped successfully")
    except Exception as e:
        logger.warning("Could not stop voice listener: %s", e)
    # Arrêter l'écoute double-clap
    try:
        arreter_ecoute_clap()
        logger.info("Double-clap listener stopped successfully")
    except Exception as e:
        logger.warning("Could not stop double-clap listener: %s", e)
    # Arrêter l'overlay visuel de navigation
    try:
        from interface_morphique.browser_overlay import stop_browser_overlay
        stop_browser_overlay()
        logger.info("Browser overlay stopped successfully")
    except Exception as e:
        logger.warning("Could not stop browser overlay: %s", e)
    # Arrêter les hooks OS réactifs
    try:
        arreter_os_hooks()
        logger.info("OS hooks stopped successfully")
    except Exception as e:
        logger.warning("Could not stop OS hooks: %s", e)
    # Arrêter le moteur morphique
    try:
        get_morphic_engine().arreter()
        logger.info("Morphic context engine stopped successfully")
    except Exception as e:
        logger.warning("Could not stop morphic engine: %s", e)




app = FastAPI(title="Jarvis API", version="1.0.0", lifespan=lifespan)

# Security & CORS configuration
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "JARVIS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

# Autorise les origines locales et toute IP du Tailnet (100.x.y.z)
TAILNET_ORIGIN_REGEX = r"^https?://(100\.[0-9]+\.[0-9]+\.[0-9]+|localhost|127\.0\.0\.1)(:[0-9]+)?$"
HELLO_ENROLLMENT_ORIGIN = "http://localhost:8000"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=TAILNET_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Jarvis-Internal-Kill"],
)

_KEY_UNLOCK_PATHS = {
    "/jarvis/security/unlock/status",
    "/jarvis/security/unlock/manual",
    "/jarvis/security/unlock/dpapi",
    "/jarvis/security/unlock/hello/options",
    "/jarvis/security/unlock/hello/verify",
}


@app.middleware("http")
async def require_datashield_unlock(request: Request, call_next):
    """Never serve profile-backed Jarvis routes while the local key is locked."""
    from datashield.profile_gate import profile_execution_gate
    request_generation = profile_execution_gate.generation
    if request.url.path.startswith("/jarvis/") and (
        WINDOWS_SESSION_LOCKED.is_set() or profile_execution_gate.locked
    ):
        if request.url.path not in _KEY_UNLOCK_PATHS:
            return Response(content='{"detail":"La session Windows est verrouillée."}', status_code=423,
                            media_type="application/json", headers={"Cache-Control": "no-store"})
    if request.url.path.startswith("/jarvis/") and request.url.path not in _KEY_UNLOCK_PATHS:
        try:
            from datashield.crypto import crypto_engine
            if not crypto_engine.is_enabled:
                return Response(
                    content='{"detail":"DataShield est verrouillé; déverrouillez le profil sur l’instance Windows."}',
                    status_code=423,
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"},
                )
        except Exception:
            logger.exception("Unable to verify DataShield unlock state")
            return Response(content='{"detail":"État DataShield indisponible."}', status_code=503,
                            media_type="application/json", headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    if (
        request.url.path.startswith("/jarvis/")
        and request.url.path != "/jarvis/security/unlock/status"
        and (
            WINDOWS_SESSION_LOCKED.is_set()
            or profile_execution_gate.locked
            or profile_execution_gate.generation != request_generation
        )
    ):
        return Response(content='{"detail":"La session Windows est verrouillée."}', status_code=423,
                        media_type="application/json", headers={"Cache-Control": "no-store"})
    return response


security = HTTPBearer(auto_error=False)
_REMOTE_SESSION_TTL_SECONDS = 30 * 60
_REMOTE_SESSION_CAPACITY = 128
_REMOTE_TOTP_FAILURE_LIMIT = 5
_REMOTE_TOTP_FAILURE_WINDOW_SECONDS = 5 * 60
_REMOTE_TOTP_COOLDOWN_SECONDS = 60
_REMOTE_TOTP_FAILURE_CAPACITY = 4096
_REMOTE_AUTH_LOCK = threading.RLock()
_REMOTE_AUTH_SESSIONS: dict[str, float] = {}
_REMOTE_TOTP_FAILURES: OrderedDict[str, tuple[int, float, float]] = OrderedDict()
_TOTP_PROFILE_LOCK = threading.RLock()
_BEARER_HASH_LOCK = threading.Lock()
_BEARER_HASH_CACHE_FINGERPRINT: bytes | None = None
_BEARER_HASH_CACHE_PHC: str | None = None
_ARGON2_BEARER_SEMAPHORE = threading.BoundedSemaphore(2)

TAILSCALE_IPV4_SUBNET = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_IPV6_SUBNET = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def est_adresse_de_confiance(client_host: str | None) -> bool:
    """Détermine si le client provient de localhost ou du réseau privé Tailscale."""
    if not client_host:
        return False
    if client_host in ("127.0.0.1", "::1", "localhost", "testclient"):
        return True
    try:
        ip = ipaddress.ip_address(client_host)
        if ip.is_loopback:
            return True
        if ip.version == 4 and ip in TAILSCALE_IPV4_SUBNET:
            return True
        if ip.version == 6 and ip in TAILSCALE_IPV6_SUBNET:
            return True
    except ValueError:
        pass
    return False


def _require_trusted_device(request: Request) -> None:
    client_host = request.client.host if request.client else None
    if not est_adresse_de_confiance(client_host):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Configuration TOTP réservée à un appareil de confiance.")


def _totp_code(secret: str, counter: int) -> str:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def _matching_totp_step(secret: str, code: str, last_accepted_step: int = -1) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current_step = int(time.time() // 30)
    matched_step = None
    for candidate in range(max(0, current_step - 1), current_step + 2):
        expected = _totp_code(secret, candidate)
        if hmac.compare_digest(expected, code) and candidate > last_accepted_step:
            matched_step = candidate if matched_step is None else max(matched_step, candidate)
    return matched_step


def _load_totp_profile():
    from context_engine.user_profile import charger_profil
    return charger_profil()


def _remote_session_is_valid(token: str) -> bool:
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _REMOTE_AUTH_LOCK:
        expiry = _REMOTE_AUTH_SESSIONS.get(token_digest)
        if expiry is None:
            return False
        if expiry <= now:
            _REMOTE_AUTH_SESSIONS.pop(token_digest, None)
            return False
        return True


def _require_remote_session_capacity(now: float | None = None) -> None:
    """Prune expired remote tokens and reject new sessions at the configured cap.

    Caller must hold _REMOTE_AUTH_LOCK so concurrent authentications cannot
    oversubscribe the in-memory session table.
    """
    current_time = time.monotonic() if now is None else now
    for digest, expiry in list(_REMOTE_AUTH_SESSIONS.items()):
        if expiry <= current_time:
            _REMOTE_AUTH_SESSIONS.pop(digest, None)
    if len(_REMOTE_AUTH_SESSIONS) < _REMOTE_SESSION_CAPACITY:
        return

    earliest_expiry = min(_REMOTE_AUTH_SESSIONS.values())
    retry_after = max(1, int(earliest_expiry - current_time + 0.999))
    raise HTTPException(
        status_code=429,
        detail="Le nombre maximal de sessions distantes est atteint; réessayez après l’expiration d’une session.",
        headers={"Retry-After": str(retry_after)},
    )


def _remote_totp_retry_after(client_ip: str) -> int:
    """Return a TOTP cooldown in seconds; caller holds _REMOTE_AUTH_LOCK."""
    state = _REMOTE_TOTP_FAILURES.get(client_ip)
    if state is None:
        return 0
    _, blocked_until, _ = state
    now = time.monotonic()
    if blocked_until > now:
        _REMOTE_TOTP_FAILURES.move_to_end(client_ip)
        return max(1, int(blocked_until - now + 0.999))
    if blocked_until:
        _REMOTE_TOTP_FAILURES.pop(client_ip, None)
    return 0


def _record_remote_totp_failure(client_ip: str) -> int:
    """Track a failed TOTP and begin a short cooldown at the configured threshold."""
    now = time.monotonic()
    state = _REMOTE_TOTP_FAILURES.get(client_ip)
    failures, blocked_until, window_started = state if state is not None else (0, 0.0, now)
    if (blocked_until and blocked_until <= now) or now - window_started >= _REMOTE_TOTP_FAILURE_WINDOW_SECONDS:
        failures = 0
        window_started = now
    failures += 1
    blocked_until = now + _REMOTE_TOTP_COOLDOWN_SECONDS if failures >= _REMOTE_TOTP_FAILURE_LIMIT else 0.0
    if client_ip not in _REMOTE_TOTP_FAILURES and len(_REMOTE_TOTP_FAILURES) >= _REMOTE_TOTP_FAILURE_CAPACITY:
        _REMOTE_TOTP_FAILURES.popitem(last=False)
    _REMOTE_TOTP_FAILURES[client_ip] = (failures, blocked_until, window_started)
    _REMOTE_TOTP_FAILURES.move_to_end(client_ip)
    return _REMOTE_TOTP_COOLDOWN_SECONDS if blocked_until else 0


def _configured_bearer_verifier() -> str | None:
    """Return the persisted Argon2id verifier, allowing plaintext only outside production."""
    global _BEARER_HASH_CACHE_FINGERPRINT, _BEARER_HASH_CACHE_PHC
    legacy_secret = os.environ.get("JARVIS_API_KEY")
    if legacy_secret and os.environ.get("GREATOS_ENV", "").strip().casefold() == "production":
        raise RuntimeError(
            "La clé Bearer en clair est interdite en production; exécutez setup_production.py pour migrer vers JARVIS_API_KEY_HASH."
        )

    persisted_verifier = os.environ.get("JARVIS_API_KEY_HASH")
    if persisted_verifier:
        if not persisted_verifier.startswith("$argon2id$"):
            raise RuntimeError("Vérificateur Bearer Argon2id invalide.")
        return persisted_verifier

    if not legacy_secret:
        return None
    fingerprint = hashlib.sha256(legacy_secret.encode("utf-8")).digest()
    with _BEARER_HASH_LOCK:
        if (
            _BEARER_HASH_CACHE_PHC is None
            or _BEARER_HASH_CACHE_FINGERPRINT is None
            or not secrets.compare_digest(fingerprint, _BEARER_HASH_CACHE_FINGERPRINT)
        ):
            from datashield.passwords import hacher_credential
            _BEARER_HASH_CACHE_PHC = hacher_credential(legacy_secret)
            _BEARER_HASH_CACHE_FINGERPRINT = fingerprint
        return _BEARER_HASH_CACHE_PHC


def _remote_bearer_matches(candidate: str) -> bool:
    """Verify the remote first factor without comparing plaintext Bearer values."""
    verifier = _configured_bearer_verifier()
    if verifier is None:
        return False
    from datashield.passwords import verifier_credential
    with _ARGON2_BEARER_SEMAPHORE:
        return verifier_credential(candidate, verifier)


def _request_session_is_valid(request: Request) -> bool:
    if WINDOWS_SESSION_LOCKED.is_set():
        return False
    client_host = request.client.host if request.client else None
    if est_adresse_de_confiance(client_host):
        return True
    scheme, separator, token = request.headers.get("authorization", "").partition(" ")
    return bool(separator and scheme.lower() == "bearer" and _remote_session_is_valid(token))


class TotpCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class ManualUnlockRequest(BaseModel):
    key: str = Field(min_length=1, max_length=65536)


class WebAuthnResponseRequest(BaseModel):
    ceremony_id: str = Field(min_length=20, max_length=128)
    credential: Dict


class WebAuthnPrfResponseRequest(WebAuthnResponseRequest):
    prf_output: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$")


def _require_webauthn_request_origin(request: Request, *, allowed: list[str] | None = None) -> str:
    origin = request.headers.get("origin", "")
    if not origin and request.url.hostname in ("localhost", "127.0.0.1", "::1"):
        origin = f"{request.url.scheme}://{request.url.netloc}"
    if not origin or not (origin in ALLOWED_ORIGINS or re.fullmatch(TAILNET_ORIGIN_REGEX, origin)):
        raise HTTPException(status_code=403, detail="Origine GreatOS non approuvée pour Windows Hello.")
    if allowed is not None and origin not in allowed:
        raise HTTPException(status_code=403, detail="Origine Windows Hello non autorisée.")
    return origin


def _require_local_hello_origin(request: Request) -> str:
    """Keep the singleton DataShield envelope bound to the packaged UI origin."""
    origin = _require_webauthn_request_origin(request)
    host = request.client.host if request.client else None
    try:
        loopback = host in ("localhost", "testclient") or bool(
            host and ipaddress.ip_address(host).is_loopback
        )
    except ValueError:
        loopback = False
    if not loopback or origin != HELLO_ENROLLMENT_ORIGIN:
        raise HTTPException(
            status_code=403,
            detail=f"Windows Hello doit être configuré depuis GreatOS ({HELLO_ENROLLMENT_ORIGIN}).",
        )
    return origin


def _require_hello_registration_origin(request: Request) -> str:
    """Allow HTTPS remote-factor credentials but keep loopback enrollment canonical."""
    origin = _require_webauthn_request_origin(request)
    host = request.client.host if request.client else None
    try:
        loopback = host in ("localhost", "testclient") or bool(
            host and ipaddress.ip_address(host).is_loopback
        )
    except ValueError:
        loopback = False
    parsed_host = (urlsplit(origin).hostname or "").lower()
    if loopback and origin != HELLO_ENROLLMENT_ORIGIN:
        raise HTTPException(
            status_code=403,
            detail=f"L’enrôlement Windows Hello local exige l’origine GreatOS {HELLO_ENROLLMENT_ORIGIN}.",
        )
    # Registration for remote-factor use must use TLS. origin_and_rp_id applies
    # the same rule during verification; this early check improves the error.
    if parsed_host not in ("localhost", "127.0.0.1", "::1") and not origin.startswith("https://"):
        raise HTTPException(status_code=403, detail="HTTPS est requis pour un credential Windows Hello distant.")
    return origin


def _require_datashield_unlocked() -> None:
    from datashield.crypto import crypto_engine
    if not crypto_engine.is_enabled:
        raise HTTPException(status_code=423, detail="DataShield est verrouillé.")


@app.get("/jarvis/security/unlock/status")
def get_unlock_status(request: Request) -> Dict:
    _require_trusted_device(request)
    from datashield.crypto import crypto_engine
    origin = request.headers.get("origin")
    hello_ready = False
    if origin and (origin in ALLOWED_ORIGINS or re.fullmatch(TAILNET_ORIGIN_REGEX, origin)):
        try:
            from datashield.windows_hello import has_prf_credential
            hello_ready = has_prf_credential(origin) and crypto_engine.is_hello_wrapped
        except Exception:
            logger.exception("Unable to read Windows Hello registry")
    return {"locked": WINDOWS_SESSION_LOCKED.is_set() or not crypto_engine.is_enabled,
            "windows_session_locked": WINDOWS_SESSION_LOCKED.is_set(), "hello_available": hello_ready,
            "manual_recovery_available": crypto_engine.is_locked or not crypto_engine.is_enabled,
            "dpapi_recovery_available": crypto_engine.dpapi_recovery_available,
            "key_store_mode": crypto_engine.windows_key_store_mode}


@app.post("/jarvis/security/unlock/dpapi")
def unlock_datashield_with_dpapi(request: Request) -> Dict:
    """Recover a locked local profile from its CurrentUser DPAPI copy, without exporting its key."""
    _require_trusted_device(request)
    client_host = request.client.host if request.client else None
    try:
        is_loopback = client_host in ("localhost", "testclient") or bool(
            client_host and ipaddress.ip_address(client_host).is_loopback
        )
    except ValueError:
        is_loopback = False
    origin = request.headers.get("origin", "")
    if not is_loopback or (origin and not re.fullmatch(
        r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", origin
    )):
        raise HTTPException(status_code=403, detail="La récupération DPAPI est réservée à l’instance locale.")

    from datashield.crypto import crypto_engine
    if crypto_engine.is_enabled:
        raise HTTPException(status_code=409, detail="DataShield est déjà déverrouillé.")
    if crypto_engine.is_hello_wrapped:
        raise HTTPException(status_code=409, detail="Windows Hello est actif; la récupération DPAPI est désactivée.")
    if not crypto_engine.dpapi_recovery_available:
        raise HTTPException(status_code=409, detail="Aucune copie DPAPI locale récupérable n’est disponible.")
    try:
        crypto_engine.unlock_from_key_store()
    except Exception as exc:
        logger.warning("Local DPAPI recovery failed: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Le coffre DPAPI local n’a pas pu être déverrouillé.") from exc
    try:
        _start_runtime_services(request.app)
    except Exception as exc:
        crypto_engine.lock()
        logger.exception("Unable to start GreatOS after local DPAPI recovery")
        raise HTTPException(status_code=503, detail="DataShield a été reverrouillé; GreatOS n’a pas démarré.") from exc
    return {"unlocked": crypto_engine.is_enabled}


@app.post("/jarvis/security/unlock/manual")
def unlock_datashield_manually(request: Request, body: ManualUnlockRequest) -> Dict:
    _require_trusted_device(request)
    from datashield.crypto import crypto_engine
    try:
        crypto_engine.unlock_with_manual_key(body.key)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=401, detail="La clé DataShield est invalide ou indisponible.") from exc
    try:
        _start_runtime_services(request.app)
    except Exception as exc:
        crypto_engine.lock()
        logger.exception("Unable to start GreatOS after DataShield manual unlock")
        raise HTTPException(status_code=503, detail="DataShield est déverrouillé, mais GreatOS n’a pas démarré.") from exc
    return {"unlocked": crypto_engine.is_enabled}


@app.post("/jarvis/security/unlock/hello/options")
def begin_hello_unlock(request: Request) -> Dict:
    _require_trusted_device(request)
    origin = _require_local_hello_origin(request)
    try:
        from datashield.crypto import crypto_engine
        if not crypto_engine.is_hello_wrapped:
            raise RuntimeError("La clé DataShield n’est pas encore liée à Windows Hello PRF.")
        from datashield.windows_hello import begin_key_unlock
        result = begin_key_unlock(origin)
        return result
    except Exception as exc:
        logger.info("Windows Hello unlock options unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=409, detail="Windows Hello n’est pas enrôlé pour cette origine.") from exc


@app.post("/jarvis/security/unlock/hello/verify")
def finish_hello_unlock(request: Request, body: WebAuthnPrfResponseRequest) -> Dict:
    _require_trusted_device(request)
    origin = _require_local_hello_origin(request)
    try:
        from datashield.windows_hello import finish_authentication
        if not finish_authentication(origin, body.ceremony_id, body.credential):
            raise ValueError("Windows Hello assertion was not verified")
        from datashield.crypto import crypto_engine
        crypto_engine.unlock_with_hello_prf(body.prf_output)
    except Exception as exc:
        logger.info("Windows Hello unlock rejected: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="La vérification Windows Hello a échoué.") from exc
    try:
        _start_runtime_services(request.app)
    except Exception as exc:
        crypto_engine.lock()
        logger.exception("Unable to start GreatOS after Windows Hello unlock")
        raise HTTPException(status_code=503, detail="Windows Hello a validé l’accès, mais GreatOS n’a pas démarré.") from exc
    return {"unlocked": crypto_engine.is_enabled}


@app.get("/jarvis/security/hello")
def get_hello_status(request: Request) -> Dict:
    _require_trusted_device(request)
    origin = _require_webauthn_request_origin(request)
    try:
        _require_hello_registration_origin(request)
        enrollment_allowed = True
    except HTTPException:
        enrollment_allowed = False
    try:
        _require_local_hello_origin(request)
        # DataShield follows the selected Windows-account DPAPI policy.
        # Windows Hello remains available as a remote authentication factor.
        key_wrapping_allowed = False
    except HTTPException:
        key_wrapping_allowed = False
    try:
        from datashield.windows_hello import has_prf_credential
        from datashield.crypto import crypto_engine
        return {"enrolled": has_prf_credential(origin), "key_wrapped": crypto_engine.is_hello_wrapped,
                "enrollment_allowed": enrollment_allowed,
                "key_wrapping_allowed": key_wrapping_allowed}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Registre Windows Hello indisponible.") from exc


@app.post("/jarvis/security/hello/enrollment")
def begin_hello_enrollment(request: Request) -> Dict:
    _require_trusted_device(request)
    _require_datashield_unlocked()
    origin = _require_hello_registration_origin(request)
    try:
        try:
            _require_local_hello_origin(request)
            require_prf = True
        except HTTPException:
            require_prf = False
        from datashield.windows_hello import begin_registration
        return begin_registration(origin, require_prf=require_prf)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Impossible de démarrer l’enrôlement Windows Hello.") from exc


@app.post("/jarvis/security/hello/enrollment/key-options")
def begin_hello_key_enrollment(request: Request) -> Dict:
    _require_trusted_device(request)
    _require_datashield_unlocked()
    _require_local_hello_origin(request)
    raise HTTPException(status_code=409, detail="DataShield suit le déverrouillage automatique du compte Windows; l’enveloppe Hello ne peut pas remplacer DPAPI.")


@app.post("/jarvis/security/hello/enrollment/key-confirm")
def confirm_hello_key_enrollment(request: Request, body: WebAuthnPrfResponseRequest) -> Dict:
    _require_trusted_device(request)
    _require_datashield_unlocked()
    _require_local_hello_origin(request)
    raise HTTPException(status_code=409, detail="DataShield suit le déverrouillage automatique du compte Windows; l’enveloppe Hello ne peut pas remplacer DPAPI.")


@app.post("/jarvis/security/hello/enrollment/confirm")
def confirm_hello_enrollment(request: Request, body: WebAuthnResponseRequest) -> Dict:
    _require_trusted_device(request)
    _require_datashield_unlocked()
    origin = _require_hello_registration_origin(request)
    try:
        try:
            _require_local_hello_origin(request)
            require_prf = True
        except HTTPException:
            require_prf = False
        from datashield.windows_hello import finish_registration
        finish_registration(origin, body.ceremony_id, body.credential, require_prf=require_prf)
        return {"enrolled": True}
    except Exception as exc:
        logger.info("Windows Hello enrollment rejected: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="L’enrôlement Windows Hello a échoué.") from exc


def _profile_security(profile: dict) -> dict:
    security_profile = profile.setdefault("security", {})
    if not isinstance(security_profile, dict):
        raise RuntimeError("Profil de sécurité invalide.")
    return security_profile


@app.get("/jarvis/auth/totp")
def get_totp_status(request: Request) -> Dict:
    """État TOTP visible uniquement depuis un appareil de confiance."""
    _require_trusted_device(request)
    try:
        with _TOTP_PROFILE_LOCK:
            profile = _load_totp_profile()
            settings = _profile_security(profile)
            return {
                "enabled": isinstance(settings.get("remote_totp"), dict),
                "enrollment_pending": isinstance(settings.get("remote_totp_pending"), dict),
            }
    except Exception as exc:
        logger.exception("Unable to read TOTP profile state")
        raise HTTPException(status_code=503, detail="La configuration TOTP chiffrée est indisponible.") from exc


@app.post("/jarvis/auth/totp/enrollment")
def begin_totp_enrollment(request: Request, response: Response) -> Dict:
    """Crée un secret TOTP en attente, restitué une fois sur un appareil de confiance."""
    _require_trusted_device(request)
    try:
        from context_engine.user_profile import transaction_profil

        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        with _TOTP_PROFILE_LOCK, transaction_profil() as profile:
            settings = _profile_security(profile)
            if isinstance(settings.get("remote_totp"), dict):
                raise HTTPException(status_code=409, detail="Le TOTP est déjà activé; réinitialisez-le depuis un appareil de confiance.")
            settings["remote_totp_pending"] = {"secret": secret}
        issuer = quote("GreatOS", safe="")
        label = quote("GreatOS", safe="")
        uri = f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
        response.headers["Cache-Control"] = "no-store"
        return {"secret": secret, "otpauth_uri": uri}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to create TOTP enrollment")
        raise HTTPException(status_code=503, detail="Impossible de créer un enrôlement TOTP chiffré.") from exc


@app.post("/jarvis/auth/totp/enrollment/confirm")
def confirm_totp_enrollment(request: Request, body: TotpCodeRequest) -> Dict:
    """N’active le TOTP qu’après vérification du code de l’application d’authentification."""
    _require_trusted_device(request)
    try:
        from context_engine.user_profile import transaction_profil

        with _TOTP_PROFILE_LOCK, transaction_profil() as profile:
            settings = _profile_security(profile)
            pending = settings.get("remote_totp_pending")
            if not isinstance(pending, dict) or not isinstance(pending.get("secret"), str):
                raise HTTPException(status_code=409, detail="Aucun enrôlement TOTP en attente.")
            if isinstance(settings.get("remote_totp"), dict):
                raise HTTPException(status_code=409, detail="Le TOTP est déjà activé.")
            accepted_step = _matching_totp_step(pending["secret"], body.code)
            if accepted_step is None:
                raise HTTPException(status_code=401, detail="Code TOTP invalide ou expiré.")
            settings["remote_totp"] = {"secret": pending["secret"], "last_accepted_step": accepted_step}
            settings.pop("remote_totp_pending", None)
        return {"enabled": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to confirm TOTP enrollment")
        raise HTTPException(status_code=503, detail="Impossible d’enregistrer l’activation TOTP.") from exc


@app.delete("/jarvis/auth/totp")
def reset_totp(request: Request) -> Dict:
    """Réinitialise la configuration TOTP depuis un appareil de confiance et révoque les sessions distantes."""
    _require_trusted_device(request)
    try:
        from context_engine.user_profile import transaction_profil

        with _REMOTE_AUTH_LOCK:
            with _TOTP_PROFILE_LOCK, transaction_profil() as profile:
                settings = _profile_security(profile)
                settings.pop("remote_totp", None)
                settings.pop("remote_totp_pending", None)
            _REMOTE_AUTH_SESSIONS.clear()
            _REMOTE_TOTP_FAILURES.clear()
        return {"enabled": False}
    except Exception as exc:
        logger.exception("Unable to reset TOTP enrollment")
        raise HTTPException(status_code=503, detail="Impossible de réinitialiser la configuration TOTP.") from exc


@app.post("/jarvis/auth/session")
def create_remote_session(
    request: Request,
    body: TotpCodeRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Dict:
    """Échange le Bearer principal et un TOTP non réutilisable contre une session distante de 30 minutes."""
    client_host = request.client.host if request.client else None
    if est_adresse_de_confiance(client_host):
        raise HTTPException(status_code=400, detail="Les appareils de confiance n’ont pas besoin de session distante.")
    if request.url.scheme != "https":
        raise HTTPException(status_code=400, detail="Une connexion HTTPS est requise pour l’authentification distante.")
    if not os.environ.get("JARVIS_API_KEY_HASH") and not os.environ.get("JARVIS_API_KEY"):
        raise HTTPException(status_code=503, detail="Authentification des accès distants non configurée.")
    rate_limit_ip = client_host or "unknown"
    with _REMOTE_AUTH_LOCK:
        retry_after = _remote_totp_retry_after(rate_limit_ip)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives d’authentification; réessayez après le délai indiqué.",
            headers={"Retry-After": str(retry_after)},
        )
    if credentials is None:
        raise HTTPException(status_code=401, detail="Identifiants distants invalides.", headers={"WWW-Authenticate": "Bearer"})
    try:
        bearer_valid = _remote_bearer_matches(credentials.credentials)
    except RuntimeError as exc:
        logger.error("Argon2id Bearer verification is unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Vérification Argon2id indisponible.") from exc
    if not bearer_valid:
        with _REMOTE_AUTH_LOCK:
            retry_after = _record_remote_totp_failure(rate_limit_ip)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Trop de tentatives d’authentification; réessayez après le délai indiqué.",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=401, detail="Identifiants distants invalides.", headers={"WWW-Authenticate": "Bearer"})

    try:
        from context_engine.user_profile import transaction_profil

        with _REMOTE_AUTH_LOCK:
            _require_remote_session_capacity()
            retry_after = _remote_totp_retry_after(rate_limit_ip)
            if retry_after:
                raise HTTPException(
                    status_code=429,
                    detail="Trop de codes TOTP incorrects; réessayez après le délai indiqué.",
                    headers={"Retry-After": str(retry_after)},
                )
            with _TOTP_PROFILE_LOCK, transaction_profil() as profile:
                settings = _profile_security(profile)
                enrollment = settings.get("remote_totp")
                if not isinstance(enrollment, dict) or not isinstance(enrollment.get("secret"), str):
                    raise HTTPException(status_code=403, detail="TOTP non configuré; enrôlez-le depuis un appareil de confiance.")
                last_step = int(enrollment.get("last_accepted_step", -1))
                accepted_step = _matching_totp_step(enrollment["secret"], body.code, last_step)
                if accepted_step is None:
                    retry_after = _record_remote_totp_failure(rate_limit_ip)
                    if retry_after:
                        raise HTTPException(
                            status_code=429,
                            detail="Trop de codes TOTP incorrects; réessayez après le délai indiqué.",
                            headers={"Retry-After": str(retry_after)},
                        )
                    raise HTTPException(status_code=401, detail="Identifiants distants invalides.", headers={"WWW-Authenticate": "Bearer"})
                enrollment["last_accepted_step"] = accepted_step
            _REMOTE_TOTP_FAILURES.pop(rate_limit_ip, None)
            token = secrets.token_urlsafe(32)
            token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            now = time.monotonic()
            _require_remote_session_capacity(now)
            _REMOTE_AUTH_SESSIONS[token_digest] = now + _REMOTE_SESSION_TTL_SECONDS
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to validate remote TOTP")
        raise HTTPException(status_code=503, detail="Le service d’authentification distante est indisponible.") from exc

    response.headers["Cache-Control"] = "no-store"
    return {"access_token": token, "token_type": "bearer", "expires_in": _REMOTE_SESSION_TTL_SECONDS}


def _remote_hello_bearer(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    client_host = request.client.host if request.client else None
    if est_adresse_de_confiance(client_host):
        raise HTTPException(status_code=400, detail="Les appareils de confiance n’ont pas besoin de session distante.")
    if request.url.scheme != "https":
        raise HTTPException(status_code=400, detail="Une connexion HTTPS est requise pour l’authentification distante.")
    if not os.environ.get("JARVIS_API_KEY_HASH") and not os.environ.get("JARVIS_API_KEY"):
        raise HTTPException(status_code=503, detail="Authentification des accès distants non configurée.")
    ip = client_host or "unknown"
    with _REMOTE_AUTH_LOCK:
        retry_after = _remote_totp_retry_after(ip)
    if retry_after:
        raise HTTPException(status_code=429, detail="Trop de tentatives; réessayez après le délai indiqué.", headers={"Retry-After": str(retry_after)})
    if credentials is None:
        raise HTTPException(status_code=401, detail="Identifiants distants invalides.", headers={"WWW-Authenticate": "Bearer"})
    try:
        valid = _remote_bearer_matches(credentials.credentials)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Vérification Argon2id indisponible.") from exc
    if not valid:
        with _REMOTE_AUTH_LOCK:
            retry_after = _record_remote_totp_failure(ip)
        raise HTTPException(status_code=429 if retry_after else 401, detail="Identifiants distants invalides.",
                            headers={"Retry-After": str(retry_after)} if retry_after else {"WWW-Authenticate": "Bearer"})
    with _REMOTE_AUTH_LOCK:
        _require_remote_session_capacity()
    return ip


@app.post("/jarvis/auth/session/hello/options")
def begin_remote_hello_session(request: Request, response: Response,
                               credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> Dict:
    """Validate the first factor and start the enrolled Hello second factor."""
    ip = _remote_hello_bearer(request, credentials)
    origin = _require_webauthn_request_origin(request)
    try:
        from datashield.windows_hello import begin_authentication
        options = begin_authentication(origin)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Windows Hello n’est pas enrôlé pour cette origine; utilisez le TOTP.") from exc
    response.headers["Cache-Control"] = "no-store"
    return options


@app.post("/jarvis/auth/session/hello")
def create_remote_hello_session(request: Request, body: WebAuthnResponseRequest, response: Response,
                                credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> Dict:
    """Issue the same short-lived session as TOTP after Bearer + Hello verification."""
    ip = _remote_hello_bearer(request, credentials)
    origin = _require_webauthn_request_origin(request)
    try:
        from datashield.windows_hello import finish_authentication
        finish_authentication(origin, body.ceremony_id, body.credential)
        with _REMOTE_AUTH_LOCK:
            _require_remote_session_capacity()
            _REMOTE_TOTP_FAILURES.pop(ip, None)
            token = secrets.token_urlsafe(32)
            token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            now = time.monotonic()
            _require_remote_session_capacity(now)
            _REMOTE_AUTH_SESSIONS[token_digest] = now + _REMOTE_SESSION_TTL_SECONDS
    except HTTPException:
        raise
    except Exception as exc:
        with _REMOTE_AUTH_LOCK:
            retry_after = _record_remote_totp_failure(ip)
        raise HTTPException(status_code=429 if retry_after else 401,
                            detail="Windows Hello distant a refusé la vérification.",
                            headers={"Retry-After": str(retry_after)} if retry_after else {}) from exc
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": token, "token_type": "bearer", "expires_in": _REMOTE_SESSION_TTL_SECONDS}


def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> bool:
    """Valide l'authentification :
    - Appareils de confiance (localhost ou Tailnet Tailscale) : accès automatique direct.
    - Autres accès distants : jeton de session éphémère obtenu avec Bearer + TOTP.
    """
    client_host = request.client.host if request.client else None
    if est_adresse_de_confiance(client_host):
        return True

    if request.url.scheme.lower() != "https":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Les accès distants non fiables exigent HTTPS.",
        )

    if not os.environ.get("JARVIS_API_KEY_HASH") and not os.environ.get("JARVIS_API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentification des accès distants non configurée",
        )
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'authentification requis pour appareil externe non approuvé",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not credentials or not _remote_session_is_valid(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session distante expirée ou invalide; authentification TOTP requise.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True

WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")
DESKTOP_DIST_DIR = Path(__file__).resolve().parent / "desktop" / "dist"
if DESKTOP_DIST_DIR.is_dir():
    app.mount("/desktop", StaticFiles(directory=DESKTOP_DIST_DIR, html=True), name="desktop")


@app.get("/hud", response_class=FileResponse)
async def serve_hud():
    """Sert le HUD Réacteur Arc Stark."""
    hud_file = WEB_DIR / "hud.html"
    if hud_file.is_file():
        return FileResponse(str(hud_file))
    raise HTTPException(status_code=404, detail="Interface HUD introuvable")


@app.get("/flux")
async def sse_hud_flux():
    """Flux d'événements SSE temps réel pour le HUD."""
    from interface_morphique.hud_controller import flux_sse
    return StreamingResponse(flux_sse(), media_type="text/event-stream")


@app.post("/hud/open")
async def open_hud_app():
    """Ouvre le HUD dans une fenêtre d'application native Edge/Chrome (--app)."""
    from interface_morphique.hud_controller import ouvrir_fenetre_app
    port = int(os.environ.get("JARVIS_API_PORT", "8000"))
    succes = ouvrir_fenetre_app(port=port)
    return {"status": "ok" if succes else "failed"}


@app.get("/api/controle")
async def get_controle_etat():
    """Retourne l'état des modèles et réglages pour le tiroir de configuration du HUD."""
    return {
        "ok": True,
        "mode": "hybride",
        "modele_actif": "GreatOS Intellect (Groq / Local)",
        "cloud": {
            "fournisseur": "groq",
            "configure": {"openai": False, "anthropic": False},
            "courants": {
                "openai": {"hybride": "gpt-4o-mini", "qualite": "gpt-4o"},
                "anthropic": {"hybride": "claude-3-5-haiku-20241022", "qualite": "claude-3-5-sonnet-20241022"},
            },
            "modeles": {"openai": [], "anthropic": []},
        },
        "local": {
            "fournisseur": "ollama",
            "actif": "qwen2.5:7b",
            "installes": [],
        },
        "voix": {
            "moteur": "piper",
            "elevenlabs": {"configure": False, "voix": "", "modele": "", "catalogue": []},
        },
    }


@app.post("/api/controle")
async def post_controle(request: Request):
    """Reçoit les actions de configuration depuis le tiroir du HUD."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = body.get("action", "")
    if action == "tester_voix":
        try:
            from jarvis.voice_output import parler_a_voix_haute
            import threading
            threading.Thread(
                target=parler_a_voix_haute,
                args=("Test de la voix Jarvis GreatOS. Tout fonctionne à merveille.",),
                daemon=True,
            ).start()
            return {"ok": True, "message": "Test vocal lancé."}
        except Exception as e:
            return {"ok": False, "message": f"Erreur vocale: {e}"}
    return {"ok": True, "message": "Réglage enregistré."}

# Global agent instance
agent = None
agent_stop_event = None
_agent_thread: threading.Thread | None = None
memoire = None
historique = None

# In-memory queues
signal_queue: deque = deque(maxlen=50)
alerts_queue: deque = deque(maxlen=50)

# Activity tracking
last_activity_time = datetime.now()

# Cache CPU pour éviter de bloquer l'event-loop asyncio dans /jarvis/status.
# Un thread de fond le rafraîchit toutes les 5 secondes avec interval=None
# (lecture instantanée du dernier échantillon psutil, pas de sleep bloquant).
_cpu_percent_cache: float = 0.0
_cpu_cache_lock = threading.Lock()


def _cpu_sampler_loop() -> None:
    """Thread de fond qui pré-chauffe et rafraîchit le cache CPU toutes les 5s."""
    global _cpu_percent_cache
    # Premier appel avec interval=1 pour initialiser les compteurs psutil,
    # mais exécuté dans ce thread dédié — pas dans la boucle asyncio.
    psutil.cpu_percent(interval=1)
    while True:
        try:
            sample = psutil.cpu_percent(interval=None)
            with _cpu_cache_lock:
                _cpu_percent_cache = sample
        except Exception:
            pass
        import time as _time
        _time.sleep(5)


def _demarrer_cpu_sampler() -> None:
    """Démarre le thread de sampling CPU en arrière-plan (daemon)."""
    t = threading.Thread(target=_cpu_sampler_loop, name="cpu-sampler", daemon=True)
    t.start()


_taskflow_scheduler_stop = threading.Event()
_DERNIERE_VERIF_UPDATE: float = 0.0


def _verifier_mises_a_jour_auto() -> None:
    """Vérifie et applique les mises à jour en arrière-plan toutes les 2 heures."""
    update_script = ROOT / "bootstrap" / "update.ps1"
    if not update_script.is_file():
        return
    try:
        logger.info("[AutoUpdate] Lancement de la recherche de mises à jour (cycle 12h)...")
        subprocess.Popen(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(update_script)],
            cwd=str(ROOT),
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        logger.debug("[AutoUpdate] Erreur lancement update.ps1: %s", exc)


def _taskflow_scheduler_loop() -> None:
    """Boucle du scheduler taskflow : vérifie rappels, automatisations et MAJ toutes les 12h."""
    import time as _time
    global _DERNIERE_VERIF_UPDATE
    from taskflow.scheduler import verifier_rappels, executer_automatisations_dues
    while not _taskflow_scheduler_stop.is_set():
        try:
            rappels = verifier_rappels()
            if rappels and rappels != "Aucun rappel du.":
                for ligne in rappels.splitlines():
                    if ligne.strip():
                        event_bus.emit("reminder", {"message": ligne.strip()})
                        logger.info("[Scheduler] Rappel déclenché : %s", ligne.strip())
        except Exception:
            logger.exception("Erreur dans le cycle rappels du taskflow scheduler")
        try:
            autos = executer_automatisations_dues()
            if autos and autos != "Aucune automatisation due.":
                logger.info("[Scheduler] Automatisations exécutées : %s", autos)
        except Exception:
            logger.exception("Erreur dans le cycle automatisations du taskflow scheduler")
        
        # Recherche de mise à jour automatique : 1 fois toutes les 12h (43200s) depuis dernière exécution
        maintenant = _time.monotonic()
        if _DERNIERE_VERIF_UPDATE == 0.0 or (maintenant - _DERNIERE_VERIF_UPDATE >= 43200.0):
            _DERNIERE_VERIF_UPDATE = maintenant
            _verifier_mises_a_jour_auto()

        _taskflow_scheduler_stop.wait(60.0)


def _demarrer_taskflow_scheduler() -> threading.Thread:
    """Démarre le thread scheduler taskflow (rappels + automatisations) en daemon."""
    _taskflow_scheduler_stop.clear()
    t = threading.Thread(target=_taskflow_scheduler_loop, name="taskflow-scheduler", daemon=True)
    t.start()
    return t


def _arreter_taskflow_scheduler() -> None:
    """Arrête proprement le scheduler taskflow."""
    _taskflow_scheduler_stop.set()


def traiter_message(message: str) -> Dict:
    """Execute the same user interaction pipeline used by the CLI.
    
    State consistency guarantees:
    - Execution is serialized by INTERACTION_LOCK (process-level lock)
    - Tools may persist data (e.g., memory.json) or modify the system during execution
    - On failure: in-memory state (historique, memoire, flags) may be partially updated
    - No global rollback: only workflow actions with an explicit safe compensation are undone
    - Error responses are clean and predictable; conversation history remains coherent
    
    This design accepts partial state updates on failure rather than pretending
    to offer transactional safety that cannot be guaranteed for external effects.
    """
    global historique, memoire
    
    try:
        reponse, intention_action = executer_interaction_utilisateur(
            message, historique, memoire
        )
        
        return {
            "response": reponse if isinstance(reponse, str) else str(reponse),
            "is_action": intention_action,
            "actions_executed": [1] if intention_action else []
        }
    except Exception as e:
        # No global rollback: tools may have persisted data or modified the system
        # beyond the explicitly compensatable actions handled by their workflow.
        # The error is reported cleanly; in-memory state may be partially updated.
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


def detect_activity() -> bool:
    """Detect keyboard/mouse activity using psutil."""
    global last_activity_time
    
    try:
        # Check for active processes that indicate user interaction
        active = False
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info.get('name', '').lower()
                # Common interactive applications
                if any(app in name for app in ['chrome', 'firefox', 'edge', 'code', 'explorer', 'notepad']):
                    active = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        if active:
            last_activity_time = datetime.now()
        
        # Consider active if activity within last 2 minutes
        return (datetime.now() - last_activity_time).total_seconds() < 120
    except Exception:
        return True  # Default to active if detection fails


# Pydantic Models
class AskRequest(BaseModel):
    message: str


class SignalRequest(BaseModel):
    device: str
    event_type: str
    payload: Dict


class ConfirmRequest(BaseModel):
    session_id: str
    action_id: str
    confirmed: bool


class OnboardingRequest(BaseModel):
    activity: str = Field(min_length=1, max_length=40)
    repetitive_task: str = Field(default="", max_length=1000)
    priority: str = Field(default="", max_length=1000)
    workflow_id: str = Field(min_length=1, max_length=64)
    language: str = Field(min_length=2, max_length=8)


@app.get("/jarvis/onboarding")
def get_onboarding(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Lit l'état de première utilisation depuis le profil DataShield chiffré."""
    from context_engine.user_profile import charger_profil
    from taskflow.preconfigured_workflows import WORKFLOWS_CATALOGUE

    profile = charger_profil()
    onboarding = profile.get("onboarding")
    workflows = [
        {"id": workflow_id, "name": workflow["nom"], "description": workflow["description"]}
        for workflow_id, workflow in WORKFLOWS_CATALOGUE.items()
    ]
    if not isinstance(onboarding, dict):
        return {"completed": False, "workflows": workflows}
    return {"completed": bool(onboarding.get("completed")), "onboarding": onboarding, "workflows": workflows}


@app.put("/jarvis/onboarding")
def save_onboarding(request: OnboardingRequest, _auth: bool = Depends(verify_api_key)) -> Dict:
    """Sauvegarde les réponses de première utilisation dans le profil chiffré."""
    from context_engine.user_profile import transaction_profil
    from taskflow.preconfigured_workflows import WORKFLOWS_CATALOGUE

    if request.activity not in {"development", "maintenance", "data_protection", "project_tracking", "other"}:
        raise HTTPException(status_code=422, detail="Activité d’onboarding invalide.")
    if request.workflow_id not in WORKFLOWS_CATALOGUE:
        raise HTTPException(status_code=422, detail="Workflow d’onboarding indisponible.")
    if request.language not in {"fr", "en"}:
        raise HTTPException(status_code=422, detail="Langue d’onboarding non prise en charge.")

    with transaction_profil() as profile:
        profile["langue"] = "français" if request.language == "fr" else "anglais"
        profile["onboarding"] = {
            "completed": True,
            "activity": request.activity,
            "repetitive_task": request.repetitive_task.strip(),
            "priority": request.priority.strip(),
            "workflow_id": request.workflow_id,
            "language": request.language,
            "provider_preference": "cloud",
            "local_fallback": True,
        }
        onboarding = profile["onboarding"]
    return {"completed": True, "onboarding": onboarding}


# Endpoints
@app.post("/jarvis/ask")
async def ask_jarvis(request: AskRequest, _auth: bool = Depends(verify_api_key)) -> Dict:
    """Process a message through Jarvis."""
    try:
        result = traiter_message(request.message)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class PlanRequest(BaseModel):
    goal: str


@app.post("/jarvis/plan")
async def create_plan(request: PlanRequest, _auth: bool = Depends(verify_api_key)) -> Dict:
    """Génère un plan d'exécution structuré sans exécuter les étapes (Core Intellect)."""
    from datashield.profile_gate import profile_execution_gate
    try:
        generation = profile_execution_gate.generation
        with profile_execution_gate.admit(generation) as admitted:
            if not admitted:
                raise HTTPException(status_code=423, detail="La session GreatOS est verrouillée.")
            from core_intellect.intellect import planifier_objectif
            from context_engine.memory import charger_memoire, normaliser_memoire
            memoire = normaliser_memoire(charger_memoire())
            if profile_execution_gate.locked or generation != profile_execution_gate.generation:
                raise HTTPException(status_code=423, detail="La session GreatOS est verrouillée.")
            plan = planifier_objectif(
                request.goal, memoire,
                execution_allowed=lambda: (
                    not profile_execution_gate.locked
                    and profile_execution_gate.generation == generation
                ),
            )
            return {
                "goal": plan.goal,
                "total_steps": len(plan.steps),
                "steps": [
                    {
                        "id": s.id,
                        "capability": s.capability,
                        "arguments": s.arguments,
                        "description": s.description,
                        "preconditions": s.preconditions,
                        "dependencies": s.dependencies,
                    }
                    for s in plan.steps
                ],
                "context": plan.context,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la planification: {str(e)}")


@app.get("/jarvis/plan/stream")
def stream_plan(
    goal: str,
    session_id: str | None = None,
    _auth: bool = Depends(verify_api_key),
):
    """Stream plan generation and execution with Server-Sent Events."""
    from datashield.profile_gate import profile_execution_gate
    generation = profile_execution_gate.generation
    active_session_id = session_id or uuid4().hex

    def event_stream():
        event_queue = event_bus.subscribe()

        def worker():
            current_thread = threading.current_thread()
            with _ACTIVE_PROFILE_WORKERS_LOCK:
                _ACTIVE_PROFILE_WORKERS.add(current_thread)
            event_bus.bind(event_queue)
            try:
                with profile_execution_gate.admit(generation) as admitted:
                    if not admitted:
                        return
                    from core_intellect.intellect import planifier_objectif
                    from jarvis.agent import orchestrer_plan
                    from context_engine.memory import charger_memoire, normaliser_memoire
                    memoire = normaliser_memoire(charger_memoire())
                    handler = StreamingConfirmationHandler(active_session_id, event_bus.emit)
                    with use_confirmation_handler(handler):
                        plan = planifier_objectif(
                            goal, memoire, on_event=event_bus.emit,
                            execution_allowed=lambda: (
                                not profile_execution_gate.locked
                                and profile_execution_gate.generation == generation
                            ),
                        )
                        orchestrer_plan(
                            plan,
                            memoire,
                            on_event=event_bus.emit,
                            expected_generation=generation,
                        )
            except Exception as e:
                event_bus.emit("error", {"message": str(e)})
            finally:
                event_queue.put({"type": "done"})
                event_bus.unbind()
                with _ACTIVE_PROFILE_WORKERS_LOCK:
                    _ACTIVE_PROFILE_WORKERS.discard(current_thread)

        thread = threading.Thread(target=worker, daemon=True)
        with _ACTIVE_PROFILE_WORKERS_LOCK:
            _ACTIVE_PROFILE_WORKERS.add(thread)
        thread.start()

        try:
            while True:
                if WINDOWS_SESSION_LOCKED.is_set():
                    break
                try:
                    event = event_queue.get(timeout=1)
                except queue.Empty:
                    continue

                if WINDOWS_SESSION_LOCKED.is_set():
                    break

                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")

                if event.get("type") == "done":
                    break
        finally:
            event_bus.unsubscribe(event_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/jarvis/stream")
def stream_jarvis(
    message: str,
    session_id: str | None = None,
    _auth: bool = Depends(verify_api_key),
):
    """Stream Jarvis events with Server-Sent Events."""
    from datashield.profile_gate import profile_execution_gate
    generation = profile_execution_gate.generation

    active_session_id = session_id or uuid4().hex

    def event_stream():
        event_queue = event_bus.subscribe()

        def worker():
            current_thread = threading.current_thread()
            with _ACTIVE_PROFILE_WORKERS_LOCK:
                _ACTIVE_PROFILE_WORKERS.add(current_thread)
            event_bus.bind(event_queue)
            
            try:
                with profile_execution_gate.admit(generation) as admitted:
                    if not admitted:
                        return
                    handler = StreamingConfirmationHandler(active_session_id, event_bus.emit)
                    with use_confirmation_handler(handler):
                        executer_interaction_utilisateur(message, historique, memoire)
            except Exception as e:
                # No global rollback: workflow compensations have already been attempted;
                # unregistered external effects may remain and the error is emitted cleanly.
                event_bus.emit("error", {"message": str(e)})
            finally:
                event_queue.put({"type": "done"})
                event_bus.unbind()
                with _ACTIVE_PROFILE_WORKERS_LOCK:
                    _ACTIVE_PROFILE_WORKERS.discard(current_thread)

        thread = threading.Thread(target=worker, daemon=True)
        with _ACTIVE_PROFILE_WORKERS_LOCK:
            _ACTIVE_PROFILE_WORKERS.add(thread)
        thread.start()

        try:
            while True:
                if WINDOWS_SESSION_LOCKED.is_set():
                    break
                try:
                    event = event_queue.get(timeout=1)
                except queue.Empty:
                    continue

                if WINDOWS_SESSION_LOCKED.is_set():
                    break

                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")

                if event.get("type") == "done":
                    break
        finally:
            event_bus.unsubscribe(event_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/jarvis/events")
def stream_background_events(
    request: Request,
    _auth: bool = Depends(verify_api_key),
):
    """Keep an SSE subscription open for proactive events outside chat turns."""
    async def event_stream():
        event_queue = event_bus.subscribe_broadcast()
        try:
            while True:
                if await request.is_disconnected() or not _request_session_is_valid(request):
                    break
                try:
                    event = await asyncio.to_thread(event_queue.get, True, 15)
                except queue.Empty:
                    yield b": keep-alive\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
        finally:
            event_bus.unsubscribe(event_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/jarvis/status")
async def get_status(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Get system status: CPU, RAM, and activity.

    cpu est lu depuis un cache rafraîchi en arrière-plan toutes les 5s.
    Cet endpoint ne bloque plus l'event-loop asyncio.
    """
    try:
        with _cpu_cache_lock:
            cpu_percent = _cpu_percent_cache
        ram_percent = psutil.virtual_memory().percent
        active = detect_activity()
        try:
            from context_engine.desktop_vision import get_vision_status
            vision_status = get_vision_status()
        except Exception as exc:
            logger.debug("Vision status unavailable: %s", exc)
            vision_status = {
                "screen_capture_supported": False,
                "interpretation_provider": None,
                "interpretation_ready": False,
                "reason": type(exc).__name__,
            }
        try:
            from datashield.crypto import crypto_engine
            encryption_status = crypto_engine.status()
        except Exception as exc:
            logger.warning("Encryption status unavailable: %s", type(exc).__name__)
            encryption_status = {"enabled": False, "reason": type(exc).__name__}

        return {
            "cpu": cpu_percent,
            "ram": ram_percent,
            "active": active,
            "voice": get_voice_input_status(),
            "vision": vision_status,
            "security": {
                "encryption": encryption_status,
                "memory_backend": os.environ.get("JARVIS_MEMORY_BACKEND", "encrypted").lower(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")


@app.get("/jarvis/progress/dashboard")
async def get_progress_dashboard(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Expose les objectifs et agrégats existants pour la vue Progress Tracker."""
    try:
        from progress_tracker.analytics import calculer_statistiques_globales
        from progress_tracker.goals import goal_manager

        statistics = calculer_statistiques_globales()
        summary = {
            key: statistics[key]
            for key in ("total", "termines", "actifs", "taux_completion", "progression_moyenne")
        }
        goals = [
            {
                "id": goal.id,
                "title": goal.titre,
                "progress": round(goal.progression_pourcentage, 1),
            }
            for goal in goal_manager.lister_objectifs()
        ]
        return {"summary": summary, "goals": goals}
    except Exception as exc:
        logger.exception("Progress dashboard data unavailable")
        raise HTTPException(status_code=500, detail="Les données Progress Tracker sont indisponibles.") from exc


@app.get("/jarvis/layout")
async def get_current_layout(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Retourne le layout contextuel actif déterminé par l'Interface Morphique."""
    try:
        from context_engine.os_hooks import get_os_hook_manager
        morphic = get_morphic_engine()
        layout = morphic.get_current_layout()
        os_ctx = get_os_hook_manager().get_current_context()
        return {
            "layout": layout.value,
            "os_context": os_ctx,
            "timestamp": time.time(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur layout: {str(e)}")


@app.post("/jarvis/signal")
async def receive_signal(request: SignalRequest, _auth: bool = Depends(verify_api_key)) -> Dict:
    """Receive a signal from an external device (e.g., TECNO)."""
    try:
        signal_data = {
            "device": request.device,
            "event_type": request.event_type,
            "payload": request.payload,
            "timestamp": datetime.now().isoformat()
        }
        signal_queue.append(signal_data)
        return {"received": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error receiving signal: {str(e)}")


@app.get("/jarvis/alerts")
async def get_alerts(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Get and clear pending alerts."""
    try:
        alerts = list(alerts_queue)
        alerts_queue.clear()
        return {"alerts": alerts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting alerts: {str(e)}")


@app.post("/jarvis/confirm")
async def confirm_action(request: ConfirmRequest, _auth: bool = Depends(verify_api_key)) -> Dict:
    """Confirm or refuse a pending action."""
    state = confirmation_manager.resolve(
        session_id=request.session_id,
        action_id=request.action_id,
        confirmed=request.confirmed,
    )
    if state == "not_found":
        raise HTTPException(status_code=404, detail="Confirmation introuvable ou expirée")
    if state == "wrong_session":
        raise HTTPException(status_code=403, detail="Confirmation liée à une autre session")
    if state == "already_resolved":
        raise HTTPException(status_code=409, detail="Confirmation déjà traitée")
    return {"processed": True, "action_id": request.action_id, "confirmed": request.confirmed}


@app.get("/jarvis/discover")
async def discover_tailscale_devices(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Discover Tailscale devices on the tailnet."""
    info = obtenir_infos_tailscale()
    if not info.get("disponible"):
        raise HTTPException(
            status_code=503,
            detail="Tailscale non disponible sur cette instance",
        )
    return info


@app.get("/jarvis/browser-sessions")
async def get_browser_sessions(_auth: bool = Depends(verify_api_key)) -> Dict:
    """Retourne l'état de toutes les sessions de navigation actives."""
    try:
        from taskflow.browser_session import get_session_manager
        manager = get_session_manager()
        sessions = manager.get_all_sessions()
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@app.get("/jarvis/browser-sessions/stream")
def stream_browser_sessions(request: Request, _auth: bool = Depends(verify_api_key)):
    """Stream les événements des sessions de navigation avec Server-Sent Events."""
    
    def event_stream():
        event_queue = queue.Queue()
        browser_event_callback = None
        
        try:
            from taskflow.browser_session import get_session_manager
            manager = get_session_manager()
            
            # Ajouter un callback pour les événements de session
            def browser_event_callback(event):
                event_queue.put({
                    "type": "browser_event",
                    "data": event
                })
            
            # S'abonner à toutes les sessions existantes
            sessions = manager.get_all_sessions()
            for session_data in sessions:
                session_id = session_data.get("session_id")
                if session_id:
                    session = manager.get_session(session_id)
                    if session:
                        session.add_event_callback(browser_event_callback)
            
            # Envoyer l'état initial
            event_queue.put({
                "type": "browser_state",
                "data": {"sessions": sessions}
            })
            
            # Boucle de streaming
            while True:
                if not _request_session_is_valid(request):
                    break
                try:
                    event = event_queue.get(timeout=30)
                    payload = json.dumps(event, ensure_ascii=False)
                    yield f"data: {payload}\n\n".encode("utf-8")
                    
                    if event.get("type") == "done":
                        break
                except queue.Empty:
                    # Heartbeat
                    yield b": heartbeat\n\n"
                    
        except GeneratorExit:
            pass
        finally:
            # Nettoyage
            if browser_event_callback:
                try:
                    from taskflow.browser_session import get_session_manager
                    manager = get_session_manager()
                    sessions = manager.get_all_sessions()
                    for session_data in sessions:
                        session_id = session_data.get("session_id")
                        if session_id:
                            session = manager.get_session(session_id)
                            if session and browser_event_callback in session.event_callbacks:
                                session.event_callbacks.remove(browser_event_callback)
                except Exception:
                    pass
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/jarvis/kill")
async def kill_jarvis(request: Request, _auth: bool = Depends(verify_api_key)) -> Dict:
    """Debug-only HTTP teardown endpoint.

    Runtime teardown is normally triggered by the internal Mode Stark command
    parser. Direct HTTP access is disabled unless JARVIS_ALLOW_HTTP_KILL=1 and
    the caller sends X-Jarvis-Internal-Kill: true.
    """
    if os.environ.get("JARVIS_ALLOW_HTTP_KILL") != "1":
        raise HTTPException(status_code=403, detail="HTTP kill endpoint disabled")
    if request.headers.get("X-Jarvis-Internal-Kill") != "true":
        raise HTTPException(status_code=403, detail="Missing internal kill guard")

    schedule_autodestruction(delay_sec=2)
    return {"status": "kill_initiated"}


def _is_loopback_bind(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def enforce_tls_1_3(context: ssl.SSLContext) -> ssl.SSLContext:
    """Set the operator-provisioned HTTPS context to TLS 1.3 minimum."""
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    return context


def validate_operator_tls_files(cert_file: str, key_file: str, server_name: str | None = None) -> set[str]:
    """Validate PEM validity, key pairing, and DNS/IP SANs required by clients."""
    try:
        certificate = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
        private_key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
        certificate_public_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_public_key = private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except Exception as exc:
        raise RuntimeError("Le certificat TLS et la clé doivent être des fichiers PEM valides et correspondants.") from exc
    if not hmac.compare_digest(certificate_public_key, private_public_key):
        raise RuntimeError("La clé privée TLS ne correspond pas au certificat opérateur.")

    valid_from = getattr(certificate, "not_valid_before_utc", None)
    if valid_from is None:
        valid_from = certificate.not_valid_before.replace(tzinfo=timezone.utc)
    valid_until = getattr(certificate, "not_valid_after_utc", None)
    if valid_until is None:
        valid_until = certificate.not_valid_after.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if not valid_from <= now < valid_until:
        raise RuntimeError("Le certificat TLS opérateur n'est pas actuellement valide.")

    dns_names = {name.lower().rstrip(".") for name in san.get_values_for_type(x509.DNSName)}
    ip_names = {str(address) for address in san.get_values_for_type(x509.IPAddress)}

    def covers(name: str) -> bool:
        try:
            return str(ipaddress.ip_address(name)) in ip_names
        except ValueError:
            hostname = name.lower().rstrip(".")
            if hostname in dns_names:
                return True
            labels = hostname.split(".")
            return len(labels) > 1 and any(
                entry.startswith("*.") and labels[1:] == entry[2:].split(".")
                for entry in dns_names
            )

    required_names = ["localhost"]
    if server_name:
        required_names.append(server_name)
    missing = [name for name in required_names if not covers(name)]
    if missing:
        raise RuntimeError("Le SAN du certificat TLS doit couvrir : " + ", ".join(missing))
    return dns_names | ip_names


def serve_api(host: str, port: int) -> None:
    """Start the API; non-loopback binds require an operator TLS certificate."""
    cert_file = os.environ.get("GREATOS_TLS_CERT_FILE", "").strip()
    key_file = os.environ.get("GREATOS_TLS_KEY_FILE", "").strip()
    tls_server_name = os.environ.get("GREATOS_TLS_SERVER_NAME", "").strip()
    if bool(cert_file) != bool(key_file):
        raise RuntimeError("GREATOS_TLS_CERT_FILE et GREATOS_TLS_KEY_FILE doivent être configurés ensemble.")
    if not cert_file and not _is_loopback_bind(host):
        raise RuntimeError(
            "Écoute réseau refusée sans certificat TLS opérateur. Configurez "
            "GREATOS_TLS_CERT_FILE et GREATOS_TLS_KEY_FILE; TLS 1.3 est obligatoire."
        )
    if cert_file and not _is_loopback_bind(host) and not tls_server_name:
        raise RuntimeError(
            "Écoute réseau refusée sans GREATOS_TLS_SERVER_NAME; configurez le DNS ou l'IP distante couvert(e) par le SAN TLS."
        )

    options = {}
    if cert_file:
        for label, path in (("certificat", cert_file), ("clé privée", key_file)):
            if not Path(path).is_file():
                raise RuntimeError(f"Fichier {label} TLS introuvable: {path}")
        validate_operator_tls_files(cert_file, key_file, tls_server_name or None)
        options = {
            "ssl_certfile": cert_file,
            "ssl_keyfile": key_file,
        }
    config = uvicorn.Config(app, host=host, port=port, **options)
    if cert_file:
        # Use Uvicorn's stable SSL config fields, then tighten the context
        # before Server.run() starts listening.
        config.load()
        if config.ssl is None:
            raise RuntimeError("Uvicorn n'a pas créé le contexte TLS configuré.")
        enforce_tls_1_3(config.ssl)
    uvicorn.Server(config).run()


if __name__ == "__main__":
    ts_info = obtenir_infos_tailscale()
    # Si Tailscale est actif, écoute sur 0.0.0.0 pour faciliter la connexion des appareils distants
    default_host = "0.0.0.0" if ts_info.get("disponible") else "127.0.0.1"
    host = os.environ.get("JARVIS_API_HOST", default_host)
    port = int(os.environ.get("JARVIS_API_PORT", "8000"))

    if ts_info.get("disponible"):
        local_ip = ts_info.get("self", {}).get("ip")
        hostname = ts_info.get("self", {}).get("nom")
        scheme = "https" if os.environ.get("GREATOS_TLS_CERT_FILE") else "http"
        print(f"\n🌐 Tailscale actif sur cette machine ({hostname}) :")
        print(f"   👉 URL Web locale    : {scheme}://localhost:{port}/web")
        cert_names: set[str] = set()
        if scheme == "https":
            try:
                cert_names = validate_operator_tls_files(
                    os.environ["GREATOS_TLS_CERT_FILE"], os.environ["GREATOS_TLS_KEY_FILE"],
                    os.environ.get("GREATOS_TLS_SERVER_NAME", "").strip() or None,
                )
            except (KeyError, RuntimeError):
                pass
        if local_ip and (scheme == "http" or local_ip in cert_names):
            print(f"   👉 URL Web Tailscale : {scheme}://{local_ip}:{port}/web")
        elif local_ip:
            print("   ℹ️ L'IP Tailscale n'est pas couverte par le SAN TLS; utilisez un nom certifié.")
        online_devices = [d for d in ts_info.get("devices", []) if d.get("online")]
        if online_devices:
            dev_str = ", ".join(f"{d['nom']} ({d['ip']})" for d in online_devices)
            print(f"   📱 Appareils distants connectés : {dev_str}\n")

    serve_api(host, port)
