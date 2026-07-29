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

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Force UTF-8 encoding to avoid charmap errors on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from jarvis import (
    demarrer_agent_autonome,
    event_bus,
    executer_interaction_utilisateur,
    initialiser,
)
from core.prompt import construire_prompt_action
from core.autodestruct import schedule_autodestruction
from core.confirmations import (
    StreamingConfirmationHandler,
    confirmation_manager,
    use_confirmation_handler,
)

app = FastAPI(title="Jarvis API", version="1.0.0")
WEB_DIR = Path(__file__).resolve().parent.parent / "gui" / "web"
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


def traiter_message(message: str) -> Dict:
    """Execute the same user interaction pipeline used by the CLI."""
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


@app.on_event("startup")
async def startup_event():
    """Initialize the global agent instance at startup."""
    global agent, agent_stop_event, memoire, historique
    
    try:
        memoire = initialiser()
        from rich.console import Console
        
        console = Console()
        agent, agent_stop_event, _ = demarrer_agent_autonome(memoire, console)
        
        prompt = construire_prompt_action(memoire)
        historique = [{"role": "system", "content": prompt}]
        
        print("Jarvis API server started successfully")
    except Exception as e:
        print(f"Error initializing agent: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the API autonomous watch loop when the server shuts down."""
    if agent_stop_event is not None:
        agent_stop_event.set()


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
async def ask_jarvis(request: AskRequest) -> Dict:
    """Process a message through Jarvis."""
    try:
        result = traiter_message(request.message)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/jarvis/stream")
async def stream_jarvis(message: str, session_id: str | None = None):
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
                yield f"data: {payload}\n\n"

                if event.get("type") == "done":
                    break
        finally:
            event_bus.unsubscribe(event_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/jarvis/status")
async def get_status() -> Dict:
    """Get system status: CPU, RAM, and activity."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
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
async def receive_signal(request: SignalRequest) -> Dict:
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
async def get_alerts() -> Dict:
    """Get and clear pending alerts."""
    try:
        alerts = list(alerts_queue)
        alerts_queue.clear()
        return {"alerts": alerts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting alerts: {str(e)}")


@app.post("/jarvis/confirm")
async def confirm_action(request: ConfirmRequest) -> Dict:
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
async def discover_tailscale_devices() -> Dict:
    """Discover Tailscale devices on the tailnet."""
    try:
        # Check if tailscale command is available
        try:
            subprocess.run(["tailscale", "--version"], capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            raise HTTPException(
                status_code=503,
                detail="Tailscale non disponible sur cette instance"
            )
        
        # Get Tailscale status in JSON format
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        
        status_data = json.loads(result.stdout)
        
        # Extract peer information
        devices = []
        peers = status_data.get("Peer", {})
        
        for peer_key, peer_info in peers.items():
            # Skip if offline
            if not peer_info.get("Online", False):
                continue
            
            # Get machine name
            hostname = peer_info.get("HostName", peer_info.get("DNSName", peer_key))
            
            # Get Tailscale IP (first IPv4 address)
            tailscale_ips = peer_info.get("TailscaleIPs", [])
            ip = None
            for addr in tailscale_ips:
                if ":" not in addr:  # IPv4
                    ip = addr
                    break
            
            if ip and hostname:
                devices.append({
                    "nom": hostname,
                    "ip": ip
                })
        
        return {"devices": devices}
        
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Tailscale JSON output: {str(e)}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Tailscale command timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error discovering Tailscale devices: {str(e)}")


@app.post("/jarvis/kill")
async def kill_jarvis(request: Request) -> Dict:
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
