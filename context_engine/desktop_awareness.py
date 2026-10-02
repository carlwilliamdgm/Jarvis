"""Desktop Awareness - Conscience universelle et dynamique du poste de travail pour GreatOS.

Zéro dictionnaire codé en dur. Zéro liste blanche statique.
Découverte dynamique par introspection des métadonnées de binaires Windows et du fenêtrage :
- Détection des fenêtres de premier plan et interactives
- Extraction des noms de produits officiels via VerQueryValueW / FileDescription
- Détection des applications utilisateur actives dans la session de Carl
- Primitives d'action universelles de fenêtrage (MoveWindow) et bus multimédia global
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import psutil

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
version_dll = ctypes.windll.version

# Primitives multimédias globales Windows
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


def attacher_bureau_interactif() -> bool:
    """Attache le thread courant à la station de bureau interactive Windows (winsta0\\default)."""
    try:
        hwinsta = user32.OpenWindowStationW("winsta0", False, 0x037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
            hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
                return True
    except Exception as e:
        logger.debug("Échec attachement winsta0\\default: %s", e)
    return False


def _extraire_description_binaire(chemin_exe: str) -> str:

    """Extrait dynamiquement la description officielle (FileDescription ou ProductName) d'un binaire Windows."""
    if not chemin_exe or not os.path.exists(chemin_exe):
        return ""
    try:
        size = version_dll.GetFileVersionInfoSizeW(chemin_exe, None)
        if size == 0:
            return ""
        res = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(chemin_exe, 0, size, res):
            return ""

        for codepage in ["040904b0", "040c04b0", "040904e4", "040c04e4"]:
            ptr = ctypes.c_void_p()
            length = wintypes.UINT()
            sub_block = f"\\StringFileInfo\\{codepage}\\FileDescription"
            if version_dll.VerQueryValueW(res, sub_block, ctypes.byref(ptr), ctypes.byref(length)) and length.value > 1:
                desc = ctypes.wstring_at(ptr.value).strip()
                if desc:
                    return desc

            sub_block_prod = f"\\StringFileInfo\\{codepage}\\ProductName"
            if version_dll.VerQueryValueW(res, sub_block_prod, ctypes.byref(ptr), ctypes.byref(length)) and length.value > 1:
                prod = ctypes.wstring_at(ptr.value).strip()
                if prod:
                    return prod
    except Exception:
        pass
    return ""


def obtenir_applications_utilisateur_dynamiques(limite: int = 10) -> List[Dict[str, str]]:
    """Découvre dynamiquement les applications lancées dans la session de Carl, hors services système internes."""
    applis_decouvertes = []
    pids_vus = set()

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = proc.info.get("exe") or ""
            nom_fichier = proc.info.get("name") or ""
            pid = proc.info.get("pid")

            # Filtrer les services internes Windows System32
            if not exe or "system32" in exe.lower() or "syswow64" in exe.lower():
                continue

            # Ne retenir que les applications installées dans Program Files, AppData ou profil Carl
            est_appli_user = any(d in exe.lower() for d in ["users", "program files", "appdata"])
            if not est_appli_user:
                continue

            cle_unique = nom_fichier.lower()
            if cle_unique in pids_vus:
                continue
            pids_vus.add(cle_unique)

            description = _extraire_description_binaire(exe)
            nom_affiche = description if description else Path(nom_fichier).stem

            # Ignorer les processus purement d'arrière-plan techniques connus
            if any(tech in nom_affiche.lower() for tech in ["crashpad", "gamemanager", "update", "telemetry"]):
                continue

            applis_decouvertes.append({
                "nom": nom_affiche,
                "processus": nom_fichier,
                "chemin": exe,
                "pid": str(pid),
            })

            if len(applis_decouvertes) >= limite:
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return applis_decouvertes


def obtenir_activite_bureau_universelle() -> Dict[str, Any]:
    """Capture l'état réel et dynamique des fenêtres et applications actives sur le bureau."""
    attacher_bureau_interactif()
    fenetres_actives = []


    def enum_windows_callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        titre = buff.value.strip()

        if not titre or titre in {"Program Manager", "Windows Input Experience"}:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        largeur = rect.right - rect.left
        hauteur = rect.bottom - rect.top

        if largeur <= 10 or hauteur <= 10:
            return True

        nom_process = ""
        nom_produit = ""
        try:
            proc = psutil.Process(pid.value)
            nom_process = proc.name()
            chemin_exe = proc.exe()
            nom_produit = _extraire_description_binaire(chemin_exe) or Path(nom_process).stem.capitalize()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            nom_produit = nom_process or "Application"

        fenetres_actives.append({
            "titre": titre,
            "application": nom_produit,
            "processus": nom_process,
            "pid": pid.value,
            "dimensions": f"{largeur}x{hauteur}",
            "position": f"({rect.left},{rect.top})",
        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

    # Focus actuel
    hwnd_focus = user32.GetForegroundWindow()
    focus_titre = ""
    if hwnd_focus:
        len_f = user32.GetWindowTextLengthW(hwnd_focus)
        if len_f > 0:
            buff_f = ctypes.create_unicode_buffer(len_f + 1)
            user32.GetWindowTextW(hwnd_focus, buff_f, len_f + 1)
            focus_titre = buff_f.value.strip()

    applis_session = obtenir_applications_utilisateur_dynamiques(limite=8)

    return {
        "fenetre_au_premier_plan": focus_titre,
        "fenetres_visibles": fenetres_actives[:8],
        "applications_session": applis_session,
    }


def redimensionner_ou_deplacer_fenetre(titre_partiel: str, x: int, y: int, largeur: int, hauteur: int) -> str:
    """Primitive universelle : repositionne ou redimensionne n'importe quelle fenêtre sous Windows sans distinction d'application."""
    attacher_bureau_interactif()
    cible_hwnd = None

    titre_trouve = ""

    def trouver_callback(hwnd: int, lparam: int) -> bool:
        nonlocal cible_hwnd, titre_trouve
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                t = buff.value.strip()
                if titre_partiel.lower() in t.lower():
                    cible_hwnd = hwnd
                    titre_trouve = t
                    return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(trouver_callback), 0)

    if not cible_hwnd:
        return f"Aucune fenêtre correspondant à '{titre_partiel}' n'a été trouvée sur le bureau."

    succes = user32.MoveWindow(cible_hwnd, x, y, largeur, hauteur, True)
    if succes:
        return f"Fenêtre '{titre_trouve}' repositionnée à ({x},{y}) avec dimensions {largeur}x{hauteur}."
    return f"Échec lors du redimensionnement de la fenêtre '{titre_trouve}'."


def envoyer_signal_multimedia_global(action: str) -> str:
    """Primitive universelle : émet un signal de bus multimédia global à Windows sans cibler une application spécifique."""
    mapping = {
        "pause": VK_MEDIA_PLAY_PAUSE,
        "play": VK_MEDIA_PLAY_PAUSE,
        "play_pause": VK_MEDIA_PLAY_PAUSE,
        "toggle": VK_MEDIA_PLAY_PAUSE,
        "suivant": VK_MEDIA_NEXT_TRACK,
        "next": VK_MEDIA_NEXT_TRACK,
        "precedent": VK_MEDIA_PREV_TRACK,
        "prev": VK_MEDIA_PREV_TRACK,
        "stop": VK_MEDIA_STOP,
        "mute": VK_VOLUME_MUTE,
        "volume_up": VK_VOLUME_UP,
        "volume_down": VK_VOLUME_DOWN,
    }
    code = mapping.get(action.lower().strip())
    if not code:
        return f"Action inconnue : {action}. Actions valides : {', '.join(sorted(mapping.keys()))}"

    try:
        user32.keybd_event(code, 0, KEYEVENTF_EXTENDEDKEY, 0)
        user32.keybd_event(code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        return f"Signal multimédia universel '{action}' transmis au système avec succès."
    except Exception as e:
        return f"Erreur lors de la transmission du signal multimédia : {e}"


def obtenir_contexte_bureau_compact() -> str:
    """Génère un résumé textuel ultra-compact (< 50 tokens) de l'activité réelle de la session Carl pour Core Intellect."""
    act = obtenir_activite_bureau_universelle()
    premier_plan = act.get("fenetre_au_premier_plan")
    applis = act.get("applications_session", [])

    morceaux = []
    if premier_plan:
        morceaux.append(f"Focus actif : {premier_plan[:60]}")

    if applis:
        noms = [a["nom"] for a in applis[:6]]
        morceaux.append(f"Applis en session : {', '.join(noms)}")

    return " | ".join(morceaux) if morceaux else "Session utilisateur au repos"
