"""Module de contrôle direct de Windows (Les Mains de Jarvis).

Permet à Jarvis de piloter l'environnement Windows de l'user sans intermédiaire :
- Contrôle du volume et des médias (touches multimédia virtuelles Win32)
- Lancement instantané d'applications et de projets (VS Code, Terminal, navigateur)
- Gestion des fenêtres et verrouillage du poste
- Actions développeur rapides (Git status, commit & push)
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

# Codes de touches virtuelles Windows (VK)
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3


def _appuyer_touche_virtuelle(vk_code: int) -> bool:
    """Envoie l'appui multimédia à Windows; l'effet côté application n'est pas vérifiable."""
    try:
        user32 = ctypes.windll.user32
        # Key down
        user32.keybd_event(vk_code, 0, 0, 0)
        # Key up
        user32.keybd_event(vk_code, 0, 2, 0)
        return True
    except Exception as exc:
        LOGGER.warning("[WindowsActions] Erreur touche virtuelle: %s", exc)
        return False


def controler_volume(action: str) -> str:
    """Monte, baisse ou coupe le son de Windows."""
    act = action.lower()
    if "mont" in act or "up" in act or "augment" in act:
        succes = all(_appuyer_touche_virtuelle(VK_VOLUME_UP) for _ in range(5))
        return "Commande d'augmentation du volume envoyée à Windows; effet non confirmé, monsieur." if succes else "Échec de l'envoi de la commande de volume à Windows."
    elif "baiss" in act or "down" in act or "diminu" in act:
        succes = all(_appuyer_touche_virtuelle(VK_VOLUME_DOWN) for _ in range(5))
        return "Commande de baisse du volume envoyée à Windows; effet non confirmé, monsieur." if succes else "Échec de l'envoi de la commande de volume à Windows."
    elif "muet" in act or "mute" in act or "coup" in act:
        succes = _appuyer_touche_virtuelle(VK_VOLUME_MUTE)
        return "Commande muet envoyée à Windows; état non confirmé, monsieur." if succes else "Échec de l'envoi de la commande muet à Windows."
    return "Action de volume non reconnue."


def controler_media(action: str) -> str:
    """Contrôle la lecture multimédia (Play, Pause, Suivant, Précédent)."""
    act = action.lower()
    if "suiv" in act or "next" in act:
        vk_code, message = VK_MEDIA_NEXT_TRACK, "Commande piste suivante envoyée à Windows; effet non confirmé, monsieur."
    elif "prec" in act or "préc" in act or "prev" in act:
        vk_code, message = VK_MEDIA_PREV_TRACK, "Commande piste précédente envoyée à Windows; effet non confirmé, monsieur."
    else:
        vk_code, message = VK_MEDIA_PLAY_PAUSE, "Commande lecture/pause envoyée à Windows; effet non confirmé, monsieur."
    return message if _appuyer_touche_virtuelle(vk_code) else "Échec de l'envoi de la commande multimédia à Windows."


def lancer_application(nom: str, cible: Optional[str] = None) -> str:
    """Lance une application ou ouvre un projet/dossier."""
    n = nom.lower()
    try:
        if "code" in n or "vs" in n:
            dossier = cible or str(Path.cwd())
            executable = shutil.which("code")
            if not executable:
                return "Impossible de lancer VS Code : commande 'code' introuvable dans PATH."
            subprocess.Popen([executable, dossier])
            return f"VS Code ouvert sur {Path(dossier).name}, monsieur."

        elif "terminal" in n or "powershell" in n or "console" in n:
            executable = shutil.which("wt") or shutil.which("powershell")
            if not executable:
                return "Impossible de lancer le terminal : Windows Terminal et PowerShell sont introuvables dans PATH."
            subprocess.Popen([executable])
            return "Terminal ouvert, monsieur."

        elif "explor" in n or "dossier" in n or "fichier" in n:
            chemin = cible or str(Path.cwd())
            subprocess.Popen(["explorer", chemin])
            return f"Explorateur ouvert sur {Path(chemin).name}, monsieur."

        elif "navigateur" in n or "chrome" in n or "edge" in n or "web" in n:
            url = cible or "https://google.com"
            import webbrowser
            if webbrowser.open(url):
                return f"Commande d'ouverture du navigateur envoyée pour {url}, monsieur."
            return "Windows n'a pas confirmé l'ouverture du navigateur."

        else:
            return f"Application non prise en charge : {nom}."
    except Exception as exc:
        LOGGER.exception("[WindowsActions] Échec lancement application : %s", exc)
        return f"Impossible de lancer {nom} : {exc}"


def verrouiller_poste() -> str:
    """Verrouille immédiatement la session Windows de l'utilisateur."""
    try:
        lock_workstation = ctypes.windll.user32.LockWorkStation
        lock_workstation.argtypes = []
        lock_workstation.restype = wintypes.BOOL
        if lock_workstation():
            return "Windows a accepté la demande de verrouillage, monsieur."
        return "Windows a refusé la demande de verrouillage."
    except Exception as exc:
        return f"Échec du verrouillage : {exc}"


def minimiser_tout() -> str:
    """Minimise toutes les fenêtres pour afficher le bureau."""
    try:
        # Shell.Application returns no effect status; use the process exit code.
        returncode = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(New-Object -ComObject Shell.Application).MinimizeAll()"],
            timeout=5,
            check=False,
        ).returncode
        return "Commande de minimisation exécutée par Windows, monsieur." if returncode == 0 else f"Windows a refusé la minimisation (code {returncode})."
    except Exception as exc:
        return f"Erreur : {exc}"
