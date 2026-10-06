"""OS Hooks - Interception d'événements système Windows réactive en temps réel.

Permet à GreatOS d'agir comme une véritable surcouche en recevant les notifications
d'événements de l'OS (Win32 SetWinEventHook) au lieu de faire du polling :
- Changement de fenêtre active / focus (EVENT_SYSTEM_FOREGROUND)
- Détection du mode plein écran (Layout Focus)
- Notification instantanée diffusée via l'EventBus de GreatOS
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

from core_intellect.event_bus import get_event_bus

logger = logging.getLogger(__name__)

# Constantes Win32 pour WinEvents
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

# Type de fonction callback WinEventProc
# void CALLBACK WinEventProc(HWINEVENTHOOK hWinEventHook, DWORD event, HWND hwnd, LONG idObject, LONG idChild, DWORD idEventThread, DWORD dwmsEventTime)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)


class OSHookManager:
    """Gestionnaire de hooks système natifs pour GreatOS."""

    def __init__(self):
        self._hook_handle: Optional[wintypes.HANDLE] = None
        self._hook_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._c_callback = None  # Conserver une référence pour éviter le garbage collection
        self._current_context: Dict[str, Any] = {
            "application": "Inconnue",
            "titre": "",
            "processus": "",
            "pid": 0,
            "plein_ecran": False,
            "timestamp": 0.0,
        }
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[Dict[str, Any]], None]] = []

    def get_current_context(self) -> Dict[str, Any]:
        """Retourne le dernier contexte OS intercepté."""
        with self._lock:
            return dict(self._current_context)

    def abonner_changement_contexte(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Ajoute un callback notifié lors d'un changement de contexte OS."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def _analyser_fenetre(self, hwnd: int) -> Dict[str, Any]:
        """Extrait les informations détaillées d'une fenêtre Windows (titre, process, plein écran)."""
        if not hwnd or sys.platform != "win32":
            return {}

        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        titre = ""
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            titre = buff.value.strip()

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # Vérifier si la fenêtre est en plein écran
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        est_plein_ecran = (
            rect.left <= 0
            and rect.top <= 0
            and rect.right >= screen_w
            and rect.bottom >= screen_h
        )

        nom_process = ""
        nom_produit = ""
        if pid.value > 0:
            try:
                import psutil
                from context_engine.desktop_awareness import _extraire_description_binaire

                proc = psutil.Process(pid.value)
                nom_process = proc.name()
                chemin_exe = proc.exe()
                nom_produit = (
                    _extraire_description_binaire(chemin_exe)
                    or nom_process.replace(".exe", "").capitalize()
                )
            except Exception:
                nom_produit = nom_process or "Application"

        return {
            "hwnd": hwnd,
            "titre": titre,
            "application": nom_produit or "Bureau",
            "processus": nom_process,
            "pid": pid.value,
            "plein_ecran": est_plein_ecran,
            "timestamp": time.time(),
        }

    def _on_winevent(
        self,
        hWinEventHook: wintypes.HANDLE,
        event: wintypes.DWORD,
        hwnd: wintypes.HWND,
        idObject: wintypes.LONG,
        idChild: wintypes.LONG,
        idEventThread: wintypes.DWORD,
        dwmsEventTime: wintypes.DWORD,
    ) -> None:
        """Callback C exécuté par Windows lors d'un événement WinEvent."""
        if event != EVENT_SYSTEM_FOREGROUND or not hwnd:
            return

        try:
            info = self._analyser_fenetre(hwnd)
            if not info or not info.get("titre"):
                return

            with self._lock:
                # Éviter de notifier plusieurs fois pour la même fenêtre inchangée
                if (
                    info["titre"] == self._current_context.get("titre")
                    and info["pid"] == self._current_context.get("pid")
                ):
                    return
                self._current_context = info
                subscribers = list(self._subscribers)

            # Notifier via l'EventBus global GreatOS
            try:
                get_event_bus().emit_broadcast("os_context_changed", info)
            except Exception as e:
                logger.debug("Échec broadcast event_bus: %s", e)

            # Notifier les callbacks directs
            for cb in subscribers:
                try:
                    cb(info)
                except Exception as e:
                    logger.debug("Erreur callback abonné OS hook: %s", e)

        except Exception as e:
            logger.debug("Erreur dans _on_winevent: %s", e)

    def _loop(self) -> None:
        """Boucle de messages Win32 dédiée pour maintenir les hooks actifs."""
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        self._c_callback = WINEVENTPROC(self._on_winevent)

        # Installer le hook Win32
        self._hook_handle = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            0,
            self._c_callback,
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )

        if not self._hook_handle:
            logger.warning("Impossible d'installer le hook WinEvent Win32")
            return

        logger.info("Hook Win32 EVENT_SYSTEM_FOREGROUND installé avec succès")

        # Boucle de messages Windows standard nécessaire pour la réception des WinEvents
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            # PeekMessage non bloquant avec timeout via wait
            has_msg = user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1)  # PM_REMOVE = 1
            if has_msg:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)

        # Désinstaller le hook au nettoyage
        if self._hook_handle:
            user32.UnhookWinEvent(self._hook_handle)
            self._hook_handle = None
            logger.info("Hook Win32 désinstallé proprement")

    def demarrer(self) -> bool:
        """Démarre le monitoring des événements OS dans un thread dédié."""
        if sys.platform != "win32":
            logger.info("OS Hooks: non supporté hors de Windows (mode stub)")
            return False

        if self._hook_thread and self._hook_thread.is_alive():
            return True

        self._stop_event.clear()
        self._hook_thread = threading.Thread(
            target=self._loop,
            name="GreatOS_WinEventHook",
            daemon=True,
        )
        self._hook_thread.start()
        return True

    def arreter(self) -> None:
        """Arrête le hook et libère les ressources Win32."""
        self._stop_event.set()
        if self._hook_thread and self._hook_thread.is_alive():
            self._hook_thread.join(timeout=1.0)


# Instance globale partagée
_os_hook_manager: Optional[OSHookManager] = None
_manager_lock = threading.Lock()


def get_os_hook_manager() -> OSHookManager:
    """Retourne l'instance singleton du gestionnaire d'OS hooks."""
    global _os_hook_manager
    if _os_hook_manager is None:
        with _manager_lock:
            if _os_hook_manager is None:
                _os_hook_manager = OSHookManager()
    return _os_hook_manager


def demarrer_os_hooks() -> bool:
    """Démarre l'interception temps réel des événements OS."""
    return get_os_hook_manager().demarrer()


def arreter_os_hooks() -> None:
    """Arrête l'interception des événements OS."""
    if _os_hook_manager is not None:
        _os_hook_manager.arreter()
