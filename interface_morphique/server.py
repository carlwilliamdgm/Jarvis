from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Dict, List
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
- Other external effects (file system, shell commands, external APIs) are NOT transactional
- These external effects are applied immediately with no global rollback mechanism

Error Handling:
- On exception: a clean error response is returned (HTTP 500 or SSE error event)
- In-memory state (historique, memoire, global flags) may be partially updated
- The conversation history remains coherent and usable after errors
- Global flags (mode_action_force, ATTENTE_DETAILS_STARK, etc.) have predictable post-error behavior

Why No Rollback?
- Tools can write to disk, execute shell commands, make network calls, etc.
- These external effects cannot be reliably undone after they occur
- Pretending to offer transactional safety would be misleading and dangerous
- The current design is honest: external effects persist, errors are reported cleanly

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
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

logger = logging.getLogger("jarvis.server")

# Force UTF-8 encoding to avoid charmap errors on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from core_intellect.llm_client import get_llm_client
from jarvis.agent import (
    demarrer_agent_autonome,
    event_bus,
    executer_interaction_utilisateur,
    initialiser,
)
from jarvis.voice_overlay import demarrer_overlay_vocal, arreter_overlay_vocal
from jarvis.voice_input import demarrer_ecoute_vocale, arreter_ecoute_vocale
from jarvis.clap_input import demarrer_ecoute_clap, arreter_ecoute_clap
from core_intellect.prompt import construire_prompt_action
from datashield.autodestruct import schedule_autodestruction
from datashield.confirmations import (
    StreamingConfirmationHandler,
    confirmation_manager,
    use_confirmation_handler,
)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle context manager replacing deprecated startup/shutdown events."""
    global agent, agent_stop_event, memoire, historique
    try:
        memoire = initialiser()
        llm_client = get_llm_client()
        from rich.console import Console

        console = Console()
        agent, agent_stop_event, _ = demarrer_agent_autonome(memoire, console)

        prompt = construire_prompt_action(memoire)
        historique = [{"role": "system", "content": prompt}]

        # Attacher l'état global et les services à app.state
        app.state.memoire = memoire
        app.state.llm_client = llm_client
        app.state.agent = agent
        app.state.agent_stop_event = agent_stop_event

        # Démarrer l'overlay visuel vocal
        demarrer_overlay_vocal()

        # Démarrer l'écoute vocale (wake word)
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

        # Démarrer l'overlay visuel de navigation
        try:
            from interface_morphique.browser_overlay import start_browser_overlay
            start_browser_overlay()
            logger.info("Browser overlay started successfully")
        except Exception as e:
            logger.warning("Could not start browser overlay: %s", e)

        logger.info("Jarvis API server started successfully")
        # Démarrer le thread de sampling CPU non-bloquant pour /jarvis/status
        _demarrer_cpu_sampler()
    except Exception as e:
        logger.error("Error initializing agent: %s", e)
        raise

    yield

    if agent_stop_event is not None:
        agent_stop_event.set()
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


app = FastAPI(title="Jarvis API", version="1.0.0", lifespan=lifespan)

# Security & CORS configuration
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "JARVIS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000",
    ).split(",")
    if origin.strip()
]

# Autorise les origines locales et toute IP du Tailnet (100.x.y.z)
TAILNET_ORIGIN_REGEX = r"^https?://(100\.[0-9]+\.[0-9]+\.[0-9]+|localhost|127\.0\.0\.1)(:[0-9]+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=TAILNET_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Jarvis-Internal-Kill"],
)


def obtenir_infos_tailscale() -> Dict:
    """Détecte l'IP Tailscale locale et les appareils distants connectés sur le Tailnet."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        status_data = json.loads(result.stdout)
        self_info = status_data.get("Self", {})
        self_ips = self_info.get("TailscaleIPs", [])
        local_ip = next((ip for ip in self_ips if ":" not in ip), None)
        local_hostname = self_info.get("HostName", "")

        devices = []
        peers = status_data.get("Peer", {})
        for peer_key, peer_info in peers.items():
            tailscale_ips = peer_info.get("TailscaleIPs", [])
            ip = next((addr for addr in tailscale_ips if ":" not in addr), None)
            hostname = peer_info.get("HostName", peer_info.get("DNSName", peer_key))
            is_online = peer_info.get("Online", False)
            os_type = peer_info.get("OS", "unknown")
            dns_name = peer_info.get("DNSName", "").rstrip(".")

            if ip and hostname:
                devices.append({
                    "nom": hostname,
                    "ip": ip,
                    "os": os_type,
                    "online": is_online,
                    "dns": dns_name,
                })

        return {
            "disponible": True,
            "self": {"nom": local_hostname, "ip": local_ip},
            "devices": devices,
        }
    except Exception:
        return {
            "disponible": False,
            "self": {"nom": None, "ip": None},
            "devices": [],
        }


security = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> bool:
    """Valide l'authentification par Bearer Token / API Key."""
    api_key = os.environ.get("JARVIS_API_KEY")
    if not api_key:
        return True
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'authentification manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(credentials.credentials, api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'authentification invalide",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True

WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")

# Global agent instance
agent = None
agent_stop_event = None
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


def traiter_message(message: str) -> Dict:
    """Execute the same user interaction pipeline used by the CLI.
    
    State consistency guarantees:
    - Execution is serialized by INTERACTION_LOCK (process-level lock)
    - Tools may persist data (e.g., memory.json) or modify the system during execution
    - On failure: in-memory state (historique, memoire, flags) may be partially updated
    - No transactional rollback: external effects (file writes, system changes) are NOT undone
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
        # No rollback: tools may have already persisted data or modified the system
        # The error is reported cleanly; in-memory state may be partially updated
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


@app.get("/jarvis/stream")
def stream_jarvis(
    message: str,
    session_id: str | None = None,
    _auth: bool = Depends(verify_api_key),
):
    """Stream Jarvis events with Server-Sent Events."""

    active_session_id = session_id or uuid4().hex

    def event_stream():
        event_queue = event_bus.subscribe()

        def worker():
            event_bus.bind(event_queue)
            
            try:
                handler = StreamingConfirmationHandler(active_session_id, event_bus.emit)
                with use_confirmation_handler(handler):
                    executer_interaction_utilisateur(message, historique, memoire)
            except Exception as e:
                # No rollback: tools may have already persisted data or modified the system
                # The error is emitted cleanly; in-memory state may be partially updated
                event_bus.emit("error", {"message": str(e)})
            finally:
                event_queue.put({"type": "done"})
                event_bus.unbind()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        try:
            while True:
                try:
                    event = event_queue.get(timeout=1)
                except queue.Empty:
                    continue

                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")

                if event.get("type") == "done":
                    break
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

        return {
            "cpu": cpu_percent,
            "ram": ram_percent,
            "active": active
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")


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
def stream_browser_sessions(_auth: bool = Depends(verify_api_key)):
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


if __name__ == "__main__":
    ts_info = obtenir_infos_tailscale()
    # Si Tailscale est actif, écoute sur 0.0.0.0 pour faciliter la connexion des appareils distants
    default_host = "0.0.0.0" if ts_info.get("disponible") else "127.0.0.1"
    host = os.environ.get("JARVIS_API_HOST", default_host)
    port = int(os.environ.get("JARVIS_API_PORT", "8000"))

    if ts_info.get("disponible"):
        local_ip = ts_info.get("self", {}).get("ip")
        hostname = ts_info.get("self", {}).get("nom")
        print(f"\n🌐 Tailscale actif sur cette machine ({hostname}) :")
        print(f"   👉 URL Web locale    : http://127.0.0.1:{port}/web")
        if local_ip:
            print(f"   👉 URL Web Tailscale : http://{local_ip}:{port}/web")
        online_devices = [d for d in ts_info.get("devices", []) if d.get("online")]
        if online_devices:
            dev_str = ", ".join(f"{d['nom']} ({d['ip']})" for d in online_devices)
            print(f"   📱 Appareils distants connectés : {dev_str}\n")

    uvicorn.run(app, host=host, port=port)
