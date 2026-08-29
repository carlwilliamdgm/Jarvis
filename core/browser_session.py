"""
Module de gestion de sessions de navigateur pour Jarvis.

Ce module permet à Jarvis de gérer plusieurs sessions de navigation
en parallèle, similaire à Claude dans Chrome, avec une interface visuelle
en temps réel et une communication événementielle.
"""

import asyncio
import threading
import json
import time
from typing import Dict, Optional, Any, List
from datetime import datetime
from enum import Enum
import os


class BrowserSessionState(Enum):
    """États d'une session de navigateur."""
    IDLE = "idle"
    NAVIGATING = "navigating"
    LOADING = "loading"
    INTERACTING = "interacting"
    ERROR = "error"
    CLOSED = "closed"


class BrowserSession:
    """Session de navigateur persistante avec états et événements."""
    
    def __init__(self, session_id: str, headless: bool = True):
        """
        Initialise une session de navigateur.
        
        Args:
            session_id: Identifiant unique de la session
            headless: Si True, exécute sans interface graphique
        """
        self.session_id = session_id
        self.headless = headless
        self.state = BrowserSessionState.IDLE
        self.current_url = ""
        self.current_title = ""
        self.error_message = ""
        self.last_activity = datetime.now()
        self.actions_history = []
        self.screenshot_data = None
        self.page_content = ""
        
        # Événements et callbacks
        self.event_callbacks = []
        self.lock = threading.Lock()
        
        # Thread d'exécution asynchrone
        self.browser = None
        self.loop = None
        self.thread = None
        self.running = False
        
        # Queue de commandes
        self.command_queue = asyncio.Queue()
    
    def add_event_callback(self, callback):
        """Ajoute un callback pour les événements de session."""
        self.event_callbacks.append(callback)
    
    def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """Émet un événement à tous les callbacks et au système event_bus de Jarvis."""
        event = {
            "session_id": self.session_id,
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        # Notifier les callbacks locaux
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception:
                pass
        
        # Intégrer avec le système event_bus de Jarvis si disponible
        try:
            from jarvis import event_bus
            event_bus.emit("browser_session", event)
        except ImportError:
            pass  # event_bus non disponible (mode standalone)
    
    def _update_state(self, new_state: BrowserSessionState, url: str = "", title: str = "", error: str = ""):
        """Met à jour l'état de la session et notifie les callbacks."""
        with self.lock:
            self.state = new_state
            if url:
                self.current_url = url
            if title:
                self.current_title = title
            if error:
                self.error_message = error
            self.last_activity = datetime.now()
        
        self._emit_event("state_changed", {
            "state": new_state.value,
            "url": self.current_url,
            "title": self.current_title,
            "error": self.error_message
        })
    
    def _add_action_to_history(self, action_type: str, details: str):
        """Ajoute une action à l'historique."""
        action = {
            "type": action_type,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.actions_history.append(action)
        self._emit_event("action_performed", action)
    
    async def _start_browser(self):
        """Démarre le navigateur dans le thread."""
        try:
            from capabilities.browser_automation import BrowserAutomation, BrowserType
            
            self.browser = BrowserAutomation(headless=self.headless, browser_type=BrowserType.CHROMIUM)
            await self.browser.start()
            
            # Marquer comme prêt seulement après vérification
            if self.browser.page is not None:
                self._update_state(BrowserSessionState.IDLE)
                self._emit_event("session_started", {"headless": self.headless})
            else:
                raise Exception("Le navigateur n'a pas pu être initialisé correctement")
            
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
            self._emit_event("session_error", {"error": str(e)})
    
    async def _navigate(self, url: str):
        """Navigue vers une URL."""
        self._update_state(BrowserSessionState.NAVIGATING, url=url)
        self._add_action_to_history("navigate", f"Navigation vers {url}")
        
        try:
            result = await self.browser.navigate(url)
            
            if "Navigation réussie" in result:
                title = await self.browser.get_title()
                self._update_state(BrowserSessionState.IDLE, url=url, title=title)
                
                # Capturer le contenu et le screenshot
                content = await self.browser.get_text("body")
                with self.lock:
                    self.page_content = content[:5000]  # Limiter à 5000 caractères
                
                screenshot = await self.browser.screenshot()
                with self.lock:
                    self.screenshot_data = screenshot
                
                self._emit_event("page_loaded", {
                    "url": url,
                    "title": title,
                    "content_length": len(content)
                })
                
            else:
                self._update_state(BrowserSessionState.IDLE, error=result)  # Retour à IDLE même en cas d'erreur
                
        except Exception as e:
            self._update_state(BrowserSessionState.IDLE, error=str(e))  # Retour à IDLE même en cas d'erreur
    
    async def _click(self, selector: str):
        """Clique sur un élément."""
        self._update_state(BrowserSessionState.INTERACTING)
        self._add_action_to_history("click", f"Clic sur {selector}")
        
        try:
            result = await self.browser.click(selector)
            self._update_state(BrowserSessionState.IDLE)
            self._emit_event("element_clicked", {"selector": selector, "result": result})
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
    
    async def _fill(self, selector: str, value: str):
        """Remplit un champ de formulaire."""
        self._update_state(BrowserSessionState.INTERACTING)
        self._add_action_to_history("fill", f"Remplissage de {selector}")
        
        try:
            result = await self.browser.fill(selector, value)
            self._update_state(BrowserSessionState.IDLE)
            self._emit_event("form_filled", {"selector": selector, "result": result})
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
    
    async def _take_screenshot(self):
        """Prend une capture d'écran."""
        self._add_action_to_history("screenshot", "Capture d'écran")
        
        try:
            screenshot = await self.browser.screenshot()
            with self.lock:
                self.screenshot_data = screenshot
            self._emit_event("screenshot_taken", {"screenshot": screenshot})
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
    
    async def _execute_javascript(self, script: str):
        """Exécute du JavaScript."""
        self._add_action_to_history("javascript", f"Exécution JS: {script[:50]}...")
        
        try:
            result = await self.browser.execute_javascript(script)
            self._emit_event("javascript_executed", {"result": result})
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
    
    async def _close(self):
        """Ferme la session."""
        self._update_state(BrowserSessionState.CLOSED)
        self.running = False
        
        if self.browser:
            await self.browser.close()
        
        self._emit_event("session_closed", {})
    
    def _run_loop(self):
        """Boucle d'exécution asynchrone dans le thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.running = True
        
        try:
            self.loop.run_until_complete(self._start_browser())
            
            # Boucle de maintien
            while self.running:
                self.loop.run_until_complete(asyncio.sleep(0.1))
                
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
        finally:
            if self.loop and not self.loop.is_closed():
                self.loop.run_until_complete(self._close())
                self.loop.close()
    
    def start(self):
        """Démarre la session dans un thread séparé."""
        if self.thread and self.thread.is_alive():
            return False
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        
        # Attendre que le navigateur soit prêt (max 10 secondes)
        for _ in range(100):  # 100 * 0.1s = 10 secondes
            time.sleep(0.1)
            if self.state != BrowserSessionState.IDLE and self.state != BrowserSessionState.ERROR:
                continue
            if self.state == BrowserSessionState.IDLE:
                return True
            if self.state == BrowserSessionState.ERROR:
                return False
        
        return False  # Timeout
    
    def stop(self):
        """Arrête la session."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def navigate(self, url: str):
        """Navigue vers une URL (non-bloquant)."""
        if not self.loop or not self.running:
            return False
        
        try:
            # Utiliser asyncio.run_coroutine_threadsafe correctement
            future = asyncio.run_coroutine_threadsafe(self._navigate(url), self.loop)
            # Ne pas attendre le résultat (non-bloquant)
            return True
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=f"Erreur de navigation: {str(e)}")
            return False
    
    def click(self, selector: str):
        """Clique sur un élément (non-bloquant)."""
        if not self.loop or not self.running:
            return False
        
        asyncio.run_coroutine_threadsafe(self._click(selector), self.loop)
        return True
    
    def fill(self, selector: str, value: str):
        """Remplit un champ (non-bloquant)."""
        if not self.loop or not self.running:
            return False
        
        asyncio.run_coroutine_threadsafe(self._fill(selector, value), self.loop)
        return True
    
    def screenshot(self):
        """Prend une capture (non-bloquant)."""
        if not self.loop or not self.running:
            return False
        
        asyncio.run_coroutine_threadsafe(self._take_screenshot(), self.loop)
        return True
    
    def execute_javascript(self, script: str):
        """Exécute du JavaScript (non-bloquant)."""
        if not self.loop or not self.running:
            return False
        
        asyncio.run_coroutine_threadsafe(self._execute_javascript(script), self.loop)
        return True
    
    def get_state(self) -> Dict[str, Any]:
        """Retourne l'état actuel de la session."""
        with self.lock:
            return {
                "session_id": self.session_id,
                "state": self.state.value,
                "current_url": self.current_url,
                "current_title": self.current_title,
                "error_message": self.error_message,
                "last_activity": self.last_activity.isoformat(),
                "actions_count": len(self.actions_history),
                "has_screenshot": self.screenshot_data is not None,
                "content_length": len(self.page_content)
            }
    
    def get_screenshot(self) -> Optional[str]:
        """Retourne la capture d'écran actuelle."""
        with self.lock:
            return self.screenshot_data
    
    def get_content(self) -> str:
        """Retourne le contenu de la page actuelle."""
        with self.lock:
            return self.page_content


class BrowserSessionManager:
    """Gestionnaire de sessions de navigateur multiples."""
    
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self.lock = threading.Lock()
        self.state_file = _STATE_FILE
    
    def create_session(self, session_id: str, headless: bool = True) -> BrowserSession:
        """Crée une nouvelle session de navigateur."""
        with self.lock:
            if session_id in self.sessions:
                return self.sessions[session_id]
            
            session = BrowserSession(session_id, headless)
            self.sessions[session_id] = session
            started = session.start()
            
            if not started:
                del self.sessions[session_id]
                raise Exception("Impossible de démarrer la session de navigateur")
            
            # Attendre que la session soit prête
            import time
            for _ in range(50):  # 5 secondes
                time.sleep(0.1)
                if session.state == BrowserSessionState.IDLE:
                    break
                if session.state == BrowserSessionState.ERROR:
                    del self.sessions[session_id]
                    raise Exception(f"Erreur de démarrage: {session.error_message}")
            
            self._save_state()
            return session
    
    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Retourne une session existante."""
        with self.lock:
            return self.sessions.get(session_id)
    
    def close_session(self, session_id: str):
        """Ferme une session."""
        with self.lock:
            if session_id in self.sessions:
                self.sessions[session_id].stop()
                del self.sessions[session_id]
                self._save_state()
    
    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Retourne l'état de toutes les sessions."""
        with self.lock:
            return [session.get_state() for session in self.sessions.values()]
    
    def _save_state(self):
        """Sauvegarde l'état des sessions dans un fichier."""
        try:
            state = {
                "sessions": [session.get_state() for session in self.sessions.values()],
                "timestamp": datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass
    
    def _load_state(self):
        """Charge l'état des sessions depuis un fichier."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    return state.get("sessions", [])
        except Exception:
            return []


# Instance globale du gestionnaire (singleton avec persistance)
_session_manager = None
_manager_lock = threading.Lock()
_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "browser_sessions_state.json")


def get_session_manager() -> BrowserSessionManager:
    """Retourne l'instance globale du gestionnaire de sessions (singleton)."""
    global _session_manager
    
    with _manager_lock:
        if _session_manager is None:
            _session_manager = BrowserSessionManager()
            # Charger l'état existant si disponible
            _session_manager._load_state()
        return _session_manager