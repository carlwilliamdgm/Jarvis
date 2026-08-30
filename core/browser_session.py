"""
Module de gestion de sessions de navigateur pour Jarvis.

Ce module permet à Jarvis de gérer des sessions de navigation persistantes
en parallèle ou via une session partagée par défaut, avec une interface visuelle
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
        self.state = BrowserSessionState.CLOSED
        self.current_url = ""
        self.current_title = ""
        self.error_message = ""
        self.last_activity = datetime.now()
        self.actions_history: List[Dict[str, Any]] = []
        self.screenshot_data: Optional[str] = None
        self.page_content = ""
        
        # Événements et callbacks
        self.event_callbacks: List[Any] = []
        self.lock = threading.Lock()
        self.ready_event = threading.Event()
        
        # Thread d'exécution asynchrone
        self.browser = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
    
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
        for callback in list(self.event_callbacks):
            try:
                callback(event)
            except Exception:
                pass
        
        # Intégrer avec le système event_bus de Jarvis si disponible
        try:
            from jarvis import event_bus
            event_bus.emit("browser_session", event)
        except (ImportError, Exception):
            pass
    
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
        with self.lock:
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
                self.ready_event.set()
            else:
                raise Exception("Le navigateur n'a pas pu être initialisé correctement")
            
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
            self._emit_event("session_error", {"error": str(e)})
            self.ready_event.set()
            raise
    
    async def _navigate(self, url: str) -> str:
        """Navigue vers une URL."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        
        self._update_state(BrowserSessionState.NAVIGATING, url=url)
        self._add_action_to_history("navigate", f"Navigation vers {url}")
        
        try:
            result = await self.browser.navigate(url)
            
            if "Navigation réussie" in result:
                title = await self.browser.get_title()
                self._update_state(BrowserSessionState.IDLE, url=url, title=title)
                
                # Capturer le contenu et le screenshot
                try:
                    content = await self.browser.get_text("body")
                    with self.lock:
                        self.page_content = content[:5000]
                    
                    screenshot = await self.browser.screenshot()
                    with self.lock:
                        self.screenshot_data = screenshot
                    
                    self._emit_event("page_loaded", {
                        "url": url,
                        "title": title,
                        "content_length": len(content)
                    })
                except Exception:
                    pass
                
                return result
            else:
                self._update_state(BrowserSessionState.IDLE, error=result)
                return result
                
        except Exception as e:
            err = str(e)
            self._update_state(BrowserSessionState.IDLE, error=err)
            return f"Erreur de navigation: {err}"
    
    async def _click(self, selector: str, timeout: int = 5000) -> str:
        """Clique sur un élément."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        
        self._update_state(BrowserSessionState.INTERACTING)
        self._add_action_to_history("click", f"Clic sur {selector}")
        
        try:
            result = await self.browser.click(selector, timeout=timeout)
            self._update_state(BrowserSessionState.IDLE)
            self._emit_event("element_clicked", {"selector": selector, "result": result})
            return result
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
            return f"Erreur lors du clic sur {selector}: {str(e)}"
    
    async def _fill(self, selector: str, value: str, timeout: int = 5000) -> str:
        """Remplit un champ de formulaire."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        
        self._update_state(BrowserSessionState.INTERACTING)
        self._add_action_to_history("fill", f"Remplissage de {selector}")
        
        try:
            result = await self.browser.fill(selector, value, timeout=timeout)
            self._update_state(BrowserSessionState.IDLE)
            self._emit_event("form_filled", {"selector": selector, "result": result})
            return result
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
            return f"Erreur lors du remplissage de {selector}: {str(e)}"
    
    async def _get_text(self, selector: str = "body") -> str:
        """Extrait le texte d'un élément."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.get_text(selector)
    
    async def _get_attribute(self, selector: str, attribute: str) -> str:
        """Extrait un attribut d'un élément."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.get_attribute(selector, attribute)
    
    async def _wait_for_element(self, selector: str, timeout: int = 10000) -> str:
        """Attend l'apparition d'un élément."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.wait_for_element(selector, timeout=timeout)
    
    async def _take_screenshot(self, path: Optional[str] = None, full_page: bool = False) -> str:
        """Prend une capture d'écran."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        
        self._add_action_to_history("screenshot", "Capture d'écran")
        try:
            screenshot = await self.browser.screenshot(path=path, full_page=full_page)
            with self.lock:
                self.screenshot_data = screenshot
            self._emit_event("screenshot_taken", {"screenshot": screenshot})
            return screenshot
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
            return f"Erreur lors de la capture d'écran: {str(e)}"
    
    async def _scroll(self, pixels: int = 500) -> str:
        """Scrolle la page."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.scroll(pixels=pixels)
    
    async def _execute_javascript(self, script: str) -> str:
        """Exécute du JavaScript."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        
        self._add_action_to_history("javascript", f"Exécution JS: {script[:50]}...")
        try:
            result = await self.browser.execute_javascript(script)
            self._emit_event("javascript_executed", {"result": result})
            return result
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
            return f"Erreur JavaScript: {str(e)}"
    
    async def _get_url(self) -> str:
        """Retourne l'URL actuelle."""
        if not self.browser or not self.browser.page:
            return ""
        return await self.browser.get_url()
    
    async def _get_title(self) -> str:
        """Retourne le titre de la page."""
        if not self.browser or not self.browser.page:
            return ""
        return await self.browser.get_title()
    
    async def _select_option(self, selector: str, value: str) -> str:
        """Sélectionne une option."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.select_option(selector, value)
    
    async def _check(self, selector: str) -> str:
        """Coche une case."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.check(selector)
    
    async def _uncheck(self, selector: str) -> str:
        """Décoche une case."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.uncheck(selector)
    
    async def _hover(self, selector: str) -> str:
        """Survole un élément."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        return await self.browser.hover(selector)
    
    async def _get_info(self) -> str:
        """Retourne des informations complètes sur la page."""
        if not self.browser or not self.browser.page:
            return "Erreur: navigateur non initialisé"
        
        infos = []
        infos.append("=== INFORMATIONS PAGE ===")
        infos.append(f"URL: {await self.browser.get_url()}")
        infos.append(f"Titre: {await self.browser.get_title()}")
        infos.append("\n=== CONTENU PRINCIPAL ===")
        text_content = await self.browser.get_text("body")
        infos.append(text_content[:2000])
        return "\n".join(infos)
    
    async def _close(self):
        """Ferme la session."""
        self._update_state(BrowserSessionState.CLOSED)
        self.running = False
        
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        
        self._emit_event("session_closed", {})
    
    def _run_loop(self):
        """Boucle d'exécution asynchrone dans le thread dédié."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.running = True
        
        try:
            self.loop.run_until_complete(self._start_browser())
            
            # Boucle de maintien tant que la session est active
            while self.running:
                self.loop.run_until_complete(asyncio.sleep(0.05))
                
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=str(e))
        finally:
            if self.loop and not self.loop.is_closed():
                try:
                    self.loop.run_until_complete(self._close())
                except Exception:
                    pass
                try:
                    self.loop.close()
                except Exception:
                    pass
    
    def start(self, timeout: float = 15.0) -> bool:
        """Démarre la session dans un thread séparé."""
        if self.thread and self.thread.is_alive():
            return True
        
        self.ready_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        
        # Attendre que le navigateur soit prêt
        if self.ready_event.wait(timeout=timeout):
            return self.state == BrowserSessionState.IDLE and self.browser is not None and self.browser.page is not None
        
        return False
    
    def stop(self):
        """Arrête la session."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)
    
    def is_alive(self) -> bool:
        """Vérifie si la session et son thread sont opérationnels."""
        return (
            self.running
            and self.thread is not None
            and self.thread.is_alive()
            and self.loop is not None
            and self.loop.is_running()
            and self.state != BrowserSessionState.CLOSED
            and self.state != BrowserSessionState.ERROR
        )
    
    # Méthodes d'exécution synchrone (bloquantes avec timeout)
    
    def run_sync(self, coro_fn, *args, timeout: float = 30.0, **kwargs) -> Any:
        """Exécute une coroutine sur la boucle de la session et attend le résultat."""
        if not self.is_alive():
            if not self.start():
                raise RuntimeError(f"Session '{self.session_id}' non disponible: {self.error_message or 'Arrêtée'}")
        
        future = asyncio.run_coroutine_threadsafe(coro_fn(*args, **kwargs), self.loop)
        return future.result(timeout=timeout)
    
    def navigate_sync(self, url: str, timeout: float = 35.0) -> str:
        """Navigue vers une URL et attend la fin de l'opération."""
        return self.run_sync(self._navigate, url, timeout=timeout)
    
    def click_sync(self, selector: str, timeout: float = 10.0) -> str:
        """Clique sur un élément et attend la confirmation."""
        return self.run_sync(self._click, selector, timeout=timeout)
    
    def fill_sync(self, selector: str, value: str, timeout: float = 10.0) -> str:
        """Remplit un champ et attend la confirmation."""
        return self.run_sync(self._fill, selector, value, timeout=timeout)
    
    def get_text_sync(self, selector: str = "body", timeout: float = 10.0) -> str:
        """Extrait le texte d'un sélecteur."""
        return self.run_sync(self._get_text, selector, timeout=timeout)
    
    def get_attribute_sync(self, selector: str, attribute: str, timeout: float = 10.0) -> str:
        """Extrait la valeur d'un attribut."""
        return self.run_sync(self._get_attribute, selector, attribute, timeout=timeout)
    
    def wait_for_element_sync(self, selector: str, timeout_ms: int = 10000) -> str:
        """Attend qu'un élément soit présent dans le DOM."""
        timeout_sec = (timeout_ms / 1000.0) + 2.0
        return self.run_sync(self._wait_for_element, selector, timeout_ms, timeout=timeout_sec)
    
    def screenshot_sync(self, path: Optional[str] = None, full_page: bool = False, timeout: float = 15.0) -> str:
        """Prend une capture d'écran."""
        return self.run_sync(self._take_screenshot, path, full_page, timeout=timeout)
    
    def scroll_sync(self, pixels: int = 500, timeout: float = 10.0) -> str:
        """Scrolle la page."""
        return self.run_sync(self._scroll, pixels, timeout=timeout)
    
    def execute_javascript_sync(self, script: str, timeout: float = 15.0) -> str:
        """Exécute du code JavaScript."""
        return self.run_sync(self._execute_javascript, script, timeout=timeout)
    
    def get_url_sync(self, timeout: float = 5.0) -> str:
        """Récupère l'URL courante."""
        return self.run_sync(self._get_url, timeout=timeout)
    
    def get_title_sync(self, timeout: float = 5.0) -> str:
        """Récupère le titre de la page."""
        return self.run_sync(self._get_title, timeout=timeout)
    
    def select_option_sync(self, selector: str, value: str, timeout: float = 10.0) -> str:
        """Sélectionne une option."""
        return self.run_sync(self._select_option, selector, value, timeout=timeout)
    
    def check_sync(self, selector: str, timeout: float = 10.0) -> str:
        """Coche une case."""
        return self.run_sync(self._check, selector, timeout=timeout)
    
    def uncheck_sync(self, selector: str, timeout: float = 10.0) -> str:
        """Décoche une case."""
        return self.run_sync(self._uncheck, selector, timeout=timeout)
    
    def hover_sync(self, selector: str, timeout: float = 10.0) -> str:
        """Survole un élément."""
        return self.run_sync(self._hover, selector, timeout=timeout)
    
    def get_info_sync(self, timeout: float = 15.0) -> str:
        """Récupère les informations de la page."""
        return self.run_sync(self._get_info, timeout=timeout)
    
    # Méthodes non-bloquantes (arrière-plan pour sessions multiples)
    
    def navigate(self, url: str) -> bool:
        """Navigue vers une URL (non-bloquant)."""
        if not self.is_alive():
            return False
        try:
            asyncio.run_coroutine_threadsafe(self._navigate(url), self.loop)
            return True
        except Exception as e:
            self._update_state(BrowserSessionState.ERROR, error=f"Erreur de navigation: {str(e)}")
            return False
    
    def click(self, selector: str) -> bool:
        """Clique sur un élément (non-bloquant)."""
        if not self.is_alive():
            return False
        asyncio.run_coroutine_threadsafe(self._click(selector), self.loop)
        return True
    
    def fill(self, selector: str, value: str) -> bool:
        """Remplit un champ (non-bloquant)."""
        if not self.is_alive():
            return False
        asyncio.run_coroutine_threadsafe(self._fill(selector, value), self.loop)
        return True
    
    def screenshot(self) -> bool:
        """Prend une capture (non-bloquant)."""
        if not self.is_alive():
            return False
        asyncio.run_coroutine_threadsafe(self._take_screenshot(), self.loop)
        return True
    
    def execute_javascript(self, script: str) -> bool:
        """Exécute du JavaScript (non-bloquant)."""
        if not self.is_alive():
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
    """Gestionnaire de cycle de vie de sessions de navigateur persistantes."""
    
    DEFAULT_SESSION_ID = "default"
    
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self.lock = threading.Lock()
        self.state_file = _STATE_FILE
    
    def get_default_session(self, headless: bool = True) -> BrowserSession:
        """Récupère ou initialise la session de navigation par défaut persistante."""
        with self.lock:
            session = self.sessions.get(self.DEFAULT_SESSION_ID)
            if session is not None and session.is_alive():
                if session.headless != headless:
                    session.stop()
                    del self.sessions[self.DEFAULT_SESSION_ID]
                else:
                    return session
            
            session = BrowserSession(self.DEFAULT_SESSION_ID, headless=headless)
            self.sessions[self.DEFAULT_SESSION_ID] = session
        
        started = session.start()
        if not started:
            with self.lock:
                self.sessions.pop(self.DEFAULT_SESSION_ID, None)
            raise RuntimeError(f"Impossible d'initialiser la session Chromium par défaut: {session.error_message or 'Timeout'}")
        
        self._save_state()
        return session
    
    def close_default_session(self):
        """Ferme la session par défaut."""
        self.close_session(self.DEFAULT_SESSION_ID)
    
    def create_session(self, session_id: str, headless: bool = True) -> BrowserSession:
        """Crée une nouvelle session de navigateur persistante."""
        with self.lock:
            if session_id in self.sessions:
                existing = self.sessions[session_id]
                if existing.is_alive():
                    return existing
                else:
                    existing.stop()
                    del self.sessions[session_id]
            
            session = BrowserSession(session_id, headless)
            self.sessions[session_id] = session
        
        started = session.start()
        if not started:
            with self.lock:
                self.sessions.pop(session_id, None)
            raise RuntimeError(f"Impossible de démarrer la session '{session_id}': {session.error_message or 'Timeout'}")
        
        self._save_state()
        return session
    
    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Retourne une session existante si active."""
        with self.lock:
            session = self.sessions.get(session_id)
            if session and session.is_alive():
                return session
            return None
    
    def close_session(self, session_id: str):
        """Ferme une session spécifique."""
        session = None
        with self.lock:
            if session_id in self.sessions:
                session = self.sessions.pop(session_id)
        if session:
            session.stop()
            self._save_state()
    
    def close_all_sessions(self):
        """Ferme toutes les sessions actives."""
        with self.lock:
            all_sessions = list(self.sessions.values())
            self.sessions.clear()
        
        for session in all_sessions:
            try:
                session.stop()
            except Exception:
                pass
        self._save_state()
    
    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Retourne l'état de toutes les sessions actives."""
        with self.lock:
            return [session.get_state() for session in self.sessions.values() if session.is_alive()]
    
    def _save_state(self):
        """Sauvegarde l'état des sessions dans un fichier JSON."""
        try:
            with self.lock:
                sessions_state = [s.get_state() for s in self.sessions.values()]
            state = {
                "sessions": sessions_state,
                "timestamp": datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass
    
    def _load_state(self):
        """Charge l'état des sessions depuis un fichier."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    return state.get("sessions", [])
        except Exception:
            return []


# Instance globale du gestionnaire (singleton thread-safe)
_session_manager: Optional[BrowserSessionManager] = None
_manager_lock = threading.Lock()
_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "browser_sessions_state.json")


def get_session_manager() -> BrowserSessionManager:
    """Retourne l'instance globale du gestionnaire de sessions (singleton)."""
    global _session_manager
    
    with _manager_lock:
        if _session_manager is None:
            _session_manager = BrowserSessionManager()
            _session_manager._load_state()
        return _session_manager