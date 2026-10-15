"""GreatOS System Tray Icon - Présence permanente dans la barre des tâches Windows.

Implémentation native Win32 (pywin32) pour afficher Jarvis dans la barre des tâches,
fournir un menu contextuel rapide et permettre l'accès immédiat aux surfaces de contrôle.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser
from typing import Callable, Optional

LOGGER = logging.getLogger("interface_morphique.tray")

try:
    import win32api
    import win32con
    import win32gui
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


class JarvisTrayIcon:
    """Gestionnaire d'icône système de la zone de notification Windows."""

    WM_TRAY = win32con.WM_USER + 20 if WIN32_AVAILABLE else 0

    ID_OPEN_WEB = 1001
    ID_OPEN_HUD = 1002
    ID_TOGGLE_STARK = 1003
    ID_STATUS = 1004
    ID_QUIT = 1005

    def __init__(
        self,
        web_url: str = "http://127.0.0.1:8000/web/",
        on_quit: Optional[Callable[[], None]] = None,
    ):
        self.web_url = web_url
        self.on_quit = on_quit
        self.hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.class_name = f"GreatOSTrayWindowClass_{os.getpid()}"

    def demarrer(self) -> bool:
        """Démarre le tray icon dans un thread d'arrière-plan."""
        if not WIN32_AVAILABLE or os.name != "nt":
            LOGGER.info("Tray icon désactivé (plateforme non-Windows ou pywin32 indisponible)")
            return False

        if self._thread and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_message_loop, name="greatos-tray", daemon=True)
        self._thread.start()
        LOGGER.info("Tray icon GreatOS démarré avec succès")
        return True

    def arreter(self) -> None:
        """Supprime l'icône et arrête la boucle de messages."""
        self._stop_event.set()
        if self.hwnd and WIN32_AVAILABLE:
            try:
                nid = (self.hwnd, 0)
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        self.hwnd = None

    def _run_message_loop(self) -> None:
        """Initialise la fenêtre Win32 invisible et fait tourner la pompe de messages."""
        wnd_class = win32gui.WNDCLASS()
        hinst = wnd_class.hInstance = win32api.GetModuleHandle(None)
        wnd_class.lpszClassName = self.class_name
        wnd_class.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW
        wnd_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wnd_class.hbrBackground = win32con.COLOR_WINDOW
        wnd_class.lpfnWndProc = self._wnd_proc

        try:
            win32gui.RegisterClass(wnd_class)
        except Exception as e:
            LOGGER.debug("Classe de fenêtre déjà enregistrée : %s", e)

        self.hwnd = win32gui.CreateWindow(
            self.class_name,
            "GreatOSTrayHost",
            win32con.WS_OVERLAPPED | win32con.WS_SYSMENU,
            0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT,
            0, 0, hinst, None
        )

        win32gui.UpdateWindow(self.hwnd)
        self._creer_icone()
        win32gui.PumpMessages()

    def _creer_icone(self) -> None:
        """Ajoute l'icône dans la zone de notification."""
        try:
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            nid = (self.hwnd, 0, flags, self.WM_TRAY, hicon, "J.A.R.V.I.S. | GreatOS")
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
        except Exception:
            LOGGER.exception("Impossible de créer l'icône dans la zone de notification")

    def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == self.WM_TRAY:
            if lparam == win32con.WM_LBUTTONUP or lparam == win32con.WM_LBUTTONDBLCLK:
                # Clic gauche : Ouvrir le Web Dashboard
                webbrowser.open(self.web_url)
            elif lparam == win32con.WM_RBUTTONUP:
                # Clic droit : Menu contextuel
                self._afficher_menu_contextuel()
            return 0
        elif msg == win32con.WM_COMMAND:
            cmd = win32gui.LOWORD(wparam)
            if cmd == self.ID_OPEN_WEB:
                webbrowser.open(self.web_url)
            elif cmd == self.ID_OPEN_HUD:
                try:
                    from interface_morphique.hud_controller import ouvrir_fenetre_app
                    ouvrir_fenetre_app(8000)
                except Exception:
                    webbrowser.open("http://127.0.0.1:8000/hud")
            elif cmd == self.ID_TOGGLE_STARK:
                try:
                    from datashield.safety import est_mode_stark_actif, activer_mode_stark, desactiver_mode_stark
                    if est_mode_stark_actif():
                        desactiver_mode_stark()
                    else:
                        activer_mode_stark()
                except Exception:
                    LOGGER.exception("Erreur lors de la bascule Stark")
            elif cmd == self.ID_STATUS:
                try:
                    from context_engine.windows_notifier import envoyer_toast
                    from datashield.defcon import defcon
                    from datashield.safety import est_mode_stark_actif
                    stark = "Actif" if est_mode_stark_actif() else "Inactif"
                    envoyer_toast("J.A.R.V.I.S. | État", f"DEFCON: {defcon.current_level.name} | Stark: {stark} | Port: 8000")
                except Exception:
                    pass
            elif cmd == self.ID_QUIT:
                self.arreter()
                if self.on_quit:
                    self.on_quit()
            return 0
        elif msg == win32con.WM_DESTROY:
            self.arreter()
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _afficher_menu_contextuel(self) -> None:
        """Affiche le menu contextuel flottant au niveau du curseur."""
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_OPEN_WEB, "🌐 Ouvrir J.A.R.V.I.S. (Web)")
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_OPEN_HUD, "🎙️ Afficher HUD Vocal")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        try:
            from datashield.safety import est_mode_stark_actif
            stark_txt = "⚡ Désactiver Mode Stark" if est_mode_stark_actif() else "⚡ Activer Mode Stark"
        except Exception:
            stark_txt = "⚡ Mode Stark"
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_TOGGLE_STARK, stark_txt)
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_STATUS, "🛡️ Statut Système (DEFCON)")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_QUIT, "❌ Quitter GreatOS")

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(menu, win32con.TPM_RIGHTBUTTON, pos[0], pos[1], 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)


_INSTANCE_TRAY: Optional[JarvisTrayIcon] = None


def demarrer_tray_icon(web_url: str = "http://127.0.0.1:8000/web/", on_quit: Optional[Callable[[], None]] = None) -> JarvisTrayIcon:
    """Démarre l'icône de barre des tâches GreatOS globale."""
    global _INSTANCE_TRAY
    if _INSTANCE_TRAY is None:
        _INSTANCE_TRAY = JarvisTrayIcon(web_url=web_url, on_quit=on_quit)
        _INSTANCE_TRAY.demarrer()
    return _INSTANCE_TRAY


def arreter_tray_icon() -> None:
    """Arrête l'icône de barre des tâches globale."""
    global _INSTANCE_TRAY
    if _INSTANCE_TRAY is not None:
        _INSTANCE_TRAY.arreter()
        _INSTANCE_TRAY = None
