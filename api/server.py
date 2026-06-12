from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from jarvis import AutonomousAgent, executer_agent, initialiser
from core.safety import action_bloquee, action_requiert_confirmation
from core.prompt import construire_prompt_action

app = FastAPI(title="Jarvis API", version="1.0.0")

# Global agent instance
agent = None
memoire = None
historique = None

# In-memory queues
signal_queue: deque = deque(maxlen=50)
alerts_queue: deque = deque(maxlen=50)

# Activity tracking
last_activity_time = datetime.now()


def traiter_message(message: str) -> Dict:
    """Wrapper around executer_agent for API usage."""
    global historique, memoire
    
    try:
        reponse, intention_action = executer_agent(message, historique, memoire)
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
    global agent, memoire, historique
    
    try:
        memoire = initialiser()
        from tools import OUTILS
        from rich.console import Console
        
        console = Console()
        agent = AutonomousAgent(memoire=memoire, outils=OUTILS, console=console)
        
        prompt = construire_prompt_action(memoire)
        historique = [{"role": "system", "content": prompt}]
        
        print("Jarvis API server started successfully")
    except Exception as e:
        print(f"Error initializing agent: {e}")
        raise


# Pydantic Models
class AskRequest(BaseModel):
    message: str


class SignalRequest(BaseModel):
    device: str
    event_type: str
    payload: Dict


class ConfirmRequest(BaseModel):
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
    try:
        # In a full implementation, this would interact with the safety system
        # to process the confirmation for a specific action_id
        # For now, we acknowledge the receipt
        return {
            "processed": True,
            "action_id": request.action_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing confirmation: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
