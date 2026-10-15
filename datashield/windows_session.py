"""Windows interactive-session lifecycle notifications for DataShield.

The monitor is intentionally fail-closed: if the input desktop cannot be
identified, callers must treat the Windows session as locked.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import sys
import threading
import uuid
from typing import Callable

logger = logging.getLogger(__name__)

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WTS_CONSOLE_CONNECT = 0x1
WTS_CONSOLE_DISCONNECT = 0x2
WTS_REMOTE_CONNECT = 0x3
WTS_REMOTE_DISCONNECT = 0x4
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
_POLL_TIMER_ID = 0x4752
_POLL_INTERVAL_MS = 1500


def _set_poll_timer(hwnd: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_timer = user32.SetTimer
    set_timer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    set_timer.restype = ctypes.c_size_t
    if not set_timer(hwnd, _POLL_TIMER_ID, _POLL_INTERVAL_MS, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _kill_poll_timer(hwnd: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kill_timer = user32.KillTimer
    kill_timer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    kill_timer.restype = wintypes.BOOL
    if not kill_timer(hwnd, _POLL_TIMER_ID):
        error = ctypes.get_last_error()
        if error:
            raise ctypes.WinError(error)


def input_desktop_is_unlocked() -> bool:
    """Return true only when Windows exposes the user's interactive desktop."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    # DESKTOP_READOBJECTS. Failure to inspect the input desktop is not evidence
    # that the account session is unlocked.
    desktop = user32.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return False
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not user32.GetUserObjectInformationW(
            desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
        ):
            return False
        return name.value == "Default"
    finally:
        user32.CloseDesktop(desktop)


class WindowsSessionMonitor:
    """Deliver lock/unlock/suspend transitions from an interactive WTS session."""

    def __init__(self, on_locked: Callable[[str], None], on_unlocked: Callable[[], None]) -> None:
        self._on_locked = on_locked
        self._on_unlocked = on_unlocked
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._window_handle: int | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._startup_error: BaseException | None = None
        self._state_lock = threading.RLock()
        self._reported_unlocked = False
        self._class_name = f"GreatOSSessionMonitor_{uuid.uuid4().hex}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stopped.is_set()

    def start(self, timeout: float = 10.0) -> bool:
        if sys.platform != "win32":
            return False
        if self.running:
            return True
        self._ready.clear()
        self._stopped.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run, name="greatos-windows-session", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop(timeout=1.0)
            raise RuntimeError("Le moniteur de session Windows n’a pas démarré à temps.")
        if self._startup_error is not None:
            raise RuntimeError("Impossible d’écouter les événements de session Windows.") from self._startup_error
        return True

    def stop(self, timeout: float = 5.0) -> None:
        thread_id = self._thread_id
        if thread_id is not None and self.running:
            try:
                import win32api
                win32api.PostThreadMessage(thread_id, WM_QUIT, 0, 0)
            except Exception:
                logger.exception("Impossible d’arrêter proprement le moniteur de session Windows")
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        if thread is not None and thread.is_alive():
            raise RuntimeError("Le moniteur de session Windows ne s’est pas arrêté proprement.")

    def request_reconcile(self) -> None:
        """Ask the message pump to retry a failed asynchronous unlock bootstrap."""
        hwnd = self._window_handle
        if hwnd is None or not self.running:
            return
        try:
            with self._state_lock:
                self._reported_unlocked = False
            import win32gui
            win32gui.PostMessage(hwnd, WM_TIMER, _POLL_TIMER_ID, 0)
        except Exception:
            logger.exception("Impossible de relancer la réconciliation Windows")

    def _set_unlocked_state(self, unlocked: bool, reason: str) -> None:
        with self._state_lock:
            if self._reported_unlocked == unlocked:
                return
            # Publish only after the security callback succeeds. If teardown or
            # resume fails, the next poll retries instead of masking the failure.
            if unlocked:
                self._on_unlocked()
            else:
                self._on_locked(reason)
            self._reported_unlocked = unlocked

    def _reconcile_desktop(self, reason: str) -> None:
        try:
            self._set_unlocked_state(input_desktop_is_unlocked(), reason)
        except Exception:
            logger.exception("Échec de vérification du bureau Windows; verrouillage par précaution")
            self._set_unlocked_state(False, reason)

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        import win32con
        import win32gui
        import win32ts

        if message == WM_WTSSESSION_CHANGE:
            if wparam in (WTS_SESSION_LOCK, WTS_SESSION_LOGOFF, WTS_CONSOLE_DISCONNECT,
                          WTS_REMOTE_DISCONNECT):
                reasons = {
                    WTS_SESSION_LOCK: "session_lock",
                    WTS_SESSION_LOGOFF: "session_logoff",
                    WTS_CONSOLE_DISCONNECT: "console_disconnect",
                    WTS_REMOTE_DISCONNECT: "remote_disconnect",
                }
                self._set_unlocked_state(False, reasons[wparam])
            elif wparam in (WTS_SESSION_UNLOCK, WTS_SESSION_LOGON, WTS_CONSOLE_CONNECT,
                            WTS_REMOTE_CONNECT):
                self._reconcile_desktop("session_unlock")
            return 0
        if message == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND:
                self._set_unlocked_state(False, "suspend")
                return 1
            if wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                self._reconcile_desktop("resume")
                return 1
        if message == WM_TIMER and wparam == _POLL_TIMER_ID:
            self._reconcile_desktop("desktop_state_change")
            return 0
        if message == WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            try:
                win32ts.WTSUnRegisterSessionNotification(hwnd)
            except Exception:
                logger.debug("Session notification was already unregistered", exc_info=True)
            try:
                _kill_poll_timer(hwnd)
            except Exception:
                logger.debug("Session monitor timer cleanup failed", exc_info=True)
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _run(self) -> None:
        import win32api
        import win32con
        import win32gui
        import win32ts

        self._thread_id = win32api.GetCurrentThreadId()
        registered = False
        try:
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = self._class_name
            window_class.lpfnWndProc = self._window_proc
            atom = win32gui.RegisterClass(window_class)
            self._window_handle = win32gui.CreateWindow(
                self._class_name, self._class_name, 0, 0, 0, 0, 0, 0, 0,
                window_class.hInstance, None,
            )
            if not self._window_handle:
                raise RuntimeError("La fenêtre de notification Windows est indisponible.")
            win32ts.WTSRegisterSessionNotification(self._window_handle, win32ts.NOTIFY_FOR_THIS_SESSION)
            registered = True
            _set_poll_timer(self._window_handle)
            self._reconcile_desktop("monitor_start")
            # Startup is complete only after the first fail-closed state
            # reconciliation and its security callback have run.
            self._ready.set()
            win32gui.PumpMessages()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            logger.exception("Moniteur de session Windows indisponible")
            if registered and self._window_handle:
                try:
                    win32ts.WTSUnRegisterSessionNotification(self._window_handle)
                except Exception:
                    logger.debug("Session notification cleanup failed", exc_info=True)
        finally:
            # A dead message pump must never leave the profile available.
            try:
                self._set_unlocked_state(False, "monitor_stopped")
            except Exception:
                logger.exception("Impossible de reverrouiller après l’arrêt du moniteur Windows")
            if self._window_handle:
                try:
                    win32gui.DestroyWindow(self._window_handle)
                except Exception:
                    logger.debug("Session monitor window cleanup failed", exc_info=True)
            try:
                win32gui.UnregisterClass(self._class_name, win32api.GetModuleHandle(None))
            except Exception:
                logger.debug("Session monitor class cleanup failed", exc_info=True)
            self._window_handle = None
            self._thread_id = None
            self._stopped.set()

