"""Module de contrôle direct de Windows (Les Mains de Jarvis).

Permet à Jarvis de piloter l'environnement Windows de Carl sans intermédiaire :
- Contrôle du volume et des médias (touches multimédia virtuelles Win32)
- Lancement instantané d'applications et de projets (VS Code, Terminal, navigateur)
- Gestion des fenêtres et verrouillage du poste
- Actions développeur rapides (Git status, commit & push)
"""

from __future__ import annotations

import ctypes
import logging
import os
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


def _appuyer_touche_virtuelle(vk_code: int) -> None:
    """Simule l'appui sur une touche multimédia Windows via user32."""
    try:
        user32 = ctypes.windll.user32
        # Key down
        user32.keybd_event(vk_code, 0, 0, 0)
        # Key up
        user32.keybd_event(vk_code, 0, 2, 0)
    except Exception as exc:
        LOGGER.warning("[WindowsActions] Erreur touche virtuelle: %s", exc)


def controler_volume(action: str) -> str:
    """Monte, baisse ou coupe le son de Windows."""
    act = action.lower()
    if "mont" in act or "up" in act or "augment" in act:
        for _ in range(5):  # 5 crans de volume
            _appuyer_touche_virtuelle(VK_VOLUME_UP)
        return "Volume augmenté de 10%, monsieur."
    elif "baiss" in act or "down" in act or "diminu" in act:
        for _ in range(5):
            _appuyer_touche_virtuelle(VK_VOLUME_DOWN)
        return "Volume diminué, monsieur."
    elif "muet" in act or "mute" in act or "coup" in act:
        _appuyer_touche_virtuelle(VK_VOLUME_MUTE)
        return "Son coupé, monsieur."
    return "Action de volume non reconnue."


def controler_media(action: str) -> str:
    """Contrôle la lecture multimédia (Play, Pause, Suivant, Précédent)."""
    act = action.lower()
    if "suiv" in act or "next" in act:
        _appuyer_touche_virtuelle(VK_MEDIA_NEXT_TRACK)
        return "Piste suivante, monsieur."
    elif "prec" in act or "préc" in act or "prev" in act:
        _appuyer_touche_virtuelle(VK_MEDIA_PREV_TRACK)
        return "Piste précédente, monsieur."
    else:
        _appuyer_touche_virtuelle(VK_MEDIA_PLAY_PAUSE)
        return "Lecture multimédia basculée."


def lancer_application(nom: str, cible: Optional[str] = None) -> str:
    """Lance une application ou ouvre un projet/dossier."""
    n = nom.lower()
    try:
        if "code" in n or "vs" in n:
            dossier = cible or str(Path.cwd())
            subprocess.Popen(["code", dossier], shell=True)
            return f"VS Code ouvert sur {Path(dossier).name}, monsieur."

        elif "terminal" in n or "powershell" in n or "console" in n:
            subprocess.Popen(["wt"] if _commande_existe("wt") else ["powershell"], shell=True)
            return "Terminal ouvert, monsieur."

        elif "explor" in n or "dossier" in n or "fichier" in n:
            chemin = cible or str(Path.cwd())
            subprocess.Popen(["explorer", chemin])
            return f"Explorateur ouvert sur {Path(chemin).name}, monsieur."

        elif "navigateur" in n or "chrome" in n or "edge" in n or "web" in n:
            url = cible or "https://google.com"
            import webbrowser
            webbrowser.open(url)
            return f"Navigateur ouvert sur {url}, monsieur."

        else:
            # Tenter de lancer la commande telle quelle
            subprocess.Popen([nom], shell=True)
            return f"Application {nom} lancée, monsieur."
    except Exception as exc:
        LOGGER.exception("[WindowsActions] Échec lancement application : %s", exc)
        return f"Impossible de lancer {nom} : {exc}"


def verrouiller_poste() -> str:
    """Verrouille immédiatement la session Windows de l'utilisateur."""
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Poste de travail verrouillé, monsieur."
    except Exception as exc:
        return f"Échec du verrouillage : {exc}"


def minimiser_tout() -> str:
    """Minimise toutes les fenêtres pour afficher le bureau."""
    try:
        # Win + D via PowerShell / Shell.Application
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(New-Object -ComObject Shell.Application).MinimizeAll()"],
            timeout=5
        )
        return "Toutes les fenêtres ont été minimisées, monsieur."
    except Exception as exc:
        return f"Erreur : {exc}"


def _commande_existe(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None
