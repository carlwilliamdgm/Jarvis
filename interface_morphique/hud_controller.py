"""Contrôleur du HUD Réacteur Arc pour GreatOS / Jarvis.

Gère l'état visuel en temps réel (SSE), le lancement en mode application
dédiée (Edge / Chrome --app), et le positionnement Win32 au premier plan
sans vol de focus clavier (SW_SHOWNOACTIVATE).
"""
from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import AsyncGenerator
import webbrowser

LOGGER = logging.getLogger(__name__)

TITRE_FENETRE = "JARVIS · Reacteur arc"
VEILLE = "veille"
ECOUTE = "ecoute"
REFLEXION = "reflexion"
PAROLE = "parole"

_ETAT = {
    "etat": VEILLE,
    "niveau": 0.0,
    "modele": "GreatOS Intellect (Groq / Local)",
    "stt": "openWakeWord + Whisper",
    "routage": "hybride",
    "budget": None,
    "micro": False,
}

_HISTORIQUE = deque(maxlen=40)
_CLIENTS: set[queue.Queue] = set()
_VERROU = threading.Lock()
_DERNIERE_OUVERTURE = 0.0
_DELAI_REOUVERTURE = 10.0


def obtenir_etat() -> dict:
    with _VERROU:
        return dict(_ETAT)


def diffuser(evenement: dict) -> None:
    """Diffuse un événement JSON à tous les clients SSE connectés."""
    donnees = json.dumps(evenement, ensure_ascii=False)
    with _VERROU:
        morts = []
        for q in _CLIENTS:
            try:
                q.put_nowait(donnees)
            except queue.Full:
                morts.append(q)
        for q in morts:
            _CLIENTS.discard(q)


def etat(nom: str) -> None:
    """Change l'état visuel du réacteur : veille, ecoute, reflexion, parole."""
    with _VERROU:
        _ETAT["etat"] = nom
    diffuser({"t": "etat", "v": nom})


def niveau(valeur: float) -> None:
    """Règle le niveau du micro (0.0 à 1.0) pour pulser le cœur du réacteur."""
    v = max(0.0, min(float(valeur), 1.0))
    with _VERROU:
        _ETAT["niveau"] = v
    diffuser({"t": "niveau", "v": v})


def dire_vous(texte: str) -> None:
    """Ajoute la transcription utilisateur au flux du HUD."""
    ev = {"t": "vous", "texte": str(texte)}
    with _VERROU:
        _HISTORIQUE.append(ev)
    diffuser(ev)


def dire_jarvis(texte: str) -> None:
    """Ajoute la réponse de Jarvis au flux du HUD."""
    ev = {"t": "jarvis", "texte": str(texte)}
    with _VERROU:
        _HISTORIQUE.append(ev)
    diffuser(ev)


def outil(nom: str, detail: str = "") -> None:
    """Signale l'exécution d'un outil dans le flux du HUD."""
    ev = {"t": "outil", "nom": str(nom), "detail": str(detail)}
    with _VERROU:
        _HISTORIQUE.append(ev)
    diffuser(ev)


def configurer(modele: str, stt: str) -> None:
    with _VERROU:
        _ETAT["modele"] = modele
        _ETAT["stt"] = stt
    diffuser({"t": "config", "modele": modele, "stt": stt})


def micro_muet(muet: bool) -> None:
    with _VERROU:
        _ETAT["micro"] = bool(muet)
    diffuser({"t": "micro", "v": bool(muet)})


async def flux_sse() -> AsyncGenerator[str, None]:
    """Générateur SSE asynchrone pour FastAPI."""
    q: queue.Queue = queue.Queue(maxsize=100)
    with _VERROU:
        _CLIENTS.add(q)
        initial_events = [
            {"t": "config", "modele": _ETAT["modele"], "stt": _ETAT["stt"]},
            {"t": "etat", "v": _ETAT["etat"]},
            {"t": "niveau", "v": _ETAT["niveau"]},
            {"t": "micro", "v": _ETAT["micro"]},
        ]
        history = list(_HISTORIQUE)

    for ev in initial_events:
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    for ev in history:
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    try:
        while True:
            # Poll non-bloquant pour la coroutine asyncio
            try:
                donnees = q.get_nowait()
                yield f"data: {donnees}\n\n"
            except queue.Empty:
                await asyncio.sleep(0.04)
    except asyncio.CancelledError:
        pass
    finally:
        with _VERROU:
            _CLIENTS.discard(q)


# ------------------------------------------------------------- Gestion Win32
def _navigateur_application() -> str | None:
    """Trouve un exécutable Chromium (Edge ou Chrome) pour le mode fenêtré --app."""
    candidats = [
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((c for c in candidats if c and os.path.isfile(c)), None)


def ouvrir_fenetre_app(port: int = 8000) -> bool:
    """Ouvre le HUD sous forme d'application native dédiée sans bordures de navigateur."""
    global _DERNIERE_OUVERTURE
    _DERNIERE_OUVERTURE = time.monotonic()
    url = f"http://127.0.0.1:{port}/hud"

    if sys.platform == "win32":
        executable = _navigateur_application()
        if executable:
            try:
                cmd = [executable, f"--app={url}"]
                subprocess.Popen(cmd, close_fds=True)
                LOGGER.info("[HUD] Fenêtre application ouverte via %s", executable)
                return True
            except OSError as err:
                LOGGER.warning("[HUD] Impossible d'ouvrir en mode --app: %s", err)

    try:
        webbrowser.open(url)
        return True
    except Exception as err:
        LOGGER.error("[HUD] Impossible d'ouvrir dans le navigateur: %s", err)
        return False


def _user32():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
    ]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return user32


def trouver_fenetres(titre: str = TITRE_FENETRE) -> list[int]:
    """Trouve les HWND des fenêtres visibles dont le titre correspond."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    user32 = _user32()
    trouvees: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def examiner(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            longueur = user32.GetWindowTextLengthW(hwnd)
            if longueur:
                tampon = ctypes.create_unicode_buffer(longueur + 1)
                user32.GetWindowTextW(hwnd, tampon, longueur + 1)
                if titre in tampon.value:
                    trouvees.append(hwnd)
        return True

    user32.EnumWindows(examiner, 0)
    return trouvees


def mettre_au_premier_plan(port: int = 8000) -> bool:
    """Fait passer la fenêtre du HUD devant les autres SANS lui voler le focus clavier."""
    if sys.platform != "win32":
        return False
    fenetres = trouver_fenetres()
    if not fenetres:
        if time.monotonic() - _DERNIERE_OUVERTURE > _DELAI_REOUVERTURE:
            ouvrir_fenetre_app(port=port)
        return False

    try:
        user32 = _user32()
        sans_activer = 0x0001 | 0x0002 | 0x0010 | 0x0040  # NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW
        for hwnd in fenetres:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, sans_activer)  # HWND_TOPMOST
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, sans_activer)  # HWND_NOTOPMOST
        return True
    except Exception as exc:
        LOGGER.debug("[HUD] Erreur premier plan Win32 : %s", exc)
        return False
