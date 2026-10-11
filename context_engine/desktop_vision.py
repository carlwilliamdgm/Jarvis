"""Desktop Vision - Vision multimodale en direct du poste de travail pour GreatOS.

Permet à Jarvis d'analyser l'écran de l'utilisateur (ou la fenêtre active)
via capture d'écran Windows native à haute vitesse et analyse multimodale VLM (Groq qwen3.8-27b).
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import io
import importlib.util
import logging
import os
import threading
from typing import Any, Dict, Optional
from PIL import Image, ImageGrab

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# Declare pointer-sized Win32 signatures explicitly; ctypes otherwise assumes
# a 32-bit C int return value and can truncate HWND/HANDLE values on 64-bit Windows.
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.OpenWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
user32.OpenWindowStationW.restype = wintypes.HANDLE
user32.SetProcessWindowStation.argtypes = [wintypes.HANDLE]
user32.SetProcessWindowStation.restype = wintypes.BOOL
user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenDesktopW.restype = wintypes.HANDLE
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL
user32.CloseWindowStation.argtypes = [wintypes.HANDLE]
user32.CloseWindowStation.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL

_DESKTOP_HANDLE_LOCK = threading.Lock()
_INTERACTIVE_STATION = None
_INTERACTIVE_DESKTOP = None


def get_vision_status() -> Dict[str, Any]:
    """Décrit les moteurs d'interprétation cloud et locaux configurés."""
    remote_analysis_enabled = os.environ.get("GREATOS_ALLOW_REMOTE_VISION", "true").lower() in {
        "1", "true", "yes", "on",
    }
    groq_key_configured = any(
        os.environ.get(name)
        for name in ("GROQ_API_KEY", *(f"GROQ_API_KEY_{index}" for index in range(1, 6)))
    )
    groq_library_available = importlib.util.find_spec("groq") is not None
    local_model_configured = bool(os.environ.get("JARVIS_VISION_LOCAL_MODEL", "").strip())
    ollama_library_available = importlib.util.find_spec("ollama") is not None
    remote_ready = remote_analysis_enabled and groq_key_configured and groq_library_available
    local_ready = local_model_configured and ollama_library_available
    return {
        "screen_capture_supported": importlib.util.find_spec("PIL") is not None,
        "screen_capture_backend": "Pillow.ImageGrab",
        "screen_capture_runtime_verified": False,
        "remote_analysis_enabled": remote_analysis_enabled,
        "interpretation_provider": "groq" if remote_ready else "ollama" if local_ready else None,
        "provider_key_configured": groq_key_configured,
        "provider_library_available": groq_library_available,
        "remote_interpretation_ready": remote_ready,
        "local_model_configured": local_model_configured,
        "local_interpretation_ready": local_ready,
        "interpretation_ready": remote_ready or local_ready,
        "interpretation_note": (
            "L'analyse distante est désactivée par configuration; GREATOS_ALLOW_REMOTE_VISION=true l'autorise."
            if not remote_analysis_enabled
            else "Analyse Groq prioritaire; Ollama local est utilisé si un modèle visuel est configuré."
            if local_ready
            else "Analyse Groq prioritaire; configurez JARVIS_VISION_LOCAL_MODEL pour le repli local."
        ),
    }


def attacher_bureau_interactif() -> bool:
    """Attache le thread courant à la station de bureau interactive Windows (winsta0\\default).

    Permet à un service ou à un processus d'arrière-plan d'accéder au vrai bureau
    graphique de l'utilisateur interactif.
    """
    global _INTERACTIVE_STATION, _INTERACTIVE_DESKTOP
    try:
        with _DESKTOP_HANDLE_LOCK:
            if not _INTERACTIVE_STATION:
                station = user32.OpenWindowStationW("winsta0", False, 0x037F)
                if not station:
                    return False
                if not user32.SetProcessWindowStation(station):
                    user32.CloseWindowStation(station)
                    return False
                # Windows retains this process-level handle for as long as the
                # process remains attached to the interactive window station.
                _INTERACTIVE_STATION = station
            if not _INTERACTIVE_DESKTOP:
                _INTERACTIVE_DESKTOP = user32.OpenDesktopW("default", 0, False, 0x01FF)
                if not _INTERACTIVE_DESKTOP:
                    return False
            desktop = _INTERACTIVE_DESKTOP
        # Each capture thread must attach itself, but reuses the single cached
        # handle instead of leaking a new desktop handle on every screenshot.
        return bool(user32.SetThreadDesktop(desktop))
    except Exception as e:
        logger.debug("Échec lors de l'attachement à winsta0\\default : %s", e)
    return False


def capturer_ecran_live(
    zone: str = "ecran",
    qualite: int = 70,
    max_dimension: int = 1024,
) -> Dict[str, Any]:
    """Capture instantanément l'écran complet ou la fenêtre active et retourne un JPEG optimisé en base64.

    Args:
        zone: 'ecran' pour l'affichage complet, 'fenetre_active' pour rogner sur la fenêtre au premier plan.
        qualite: Qualité de compression JPEG (défaut 70 pour équilibre vitesse/détail).
        max_dimension: Dimension maximale en pixels pour limiter la charge token VLM.

    Returns:
        Dict contenant 'base64', 'largeur', 'hauteur', 'timestamp', 'zone'.
    """
    if zone not in ("ecran", "fenetre_active"):
        raise ValueError("zone doit être 'ecran' ou 'fenetre_active'")

    attacher_bureau_interactif()

    boite_rognage = None
    if zone == "fenetre_active":
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("Aucune fenêtre au premier plan n'a été détectée")
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("Impossible de lire les dimensions de la fenêtre active")
        # (left, top, right, bottom)
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 20 or h <= 20:
            raise RuntimeError("La fenêtre active n'a pas de dimensions capturables")
        boite_rognage = (rect.left, rect.top, rect.right, rect.bottom)

    img = ImageGrab.grab(bbox=boite_rognage)
    largeur_orig, hauteur_orig = img.size

    # Redimensionnement proportionnel si dépassement
    if max(largeur_orig, hauteur_orig) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=qualite, optimize=True)
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

    return {
        "base64": b64_str,
        "largeur": img.size[0],
        "hauteur": img.size[1],
        "resolution_source": f"{largeur_orig}x{hauteur_orig}",
        "timestamp": datetime.now().isoformat(),
        "zone": zone,
    }


def analyser_ecran_live(
    question: str = "Décris précisément et sobrement ce qui est visible et ouvert sur cet écran.",
    zone: str = "ecran",
) -> str:
    """Capture l'écran en direct et le soumet au modèle multimodal pour interprétation en langage naturel."""
    try:
        capture = capturer_ecran_live(zone=zone)
    except Exception as e:
        logger.warning("Échec de la capture écran locale : %s", e)
        return f"Échec de la capture écran locale; aucune image n'a été analysée ({type(e).__name__})."

    b64_image = capture["base64"]

    remote_analysis_enabled = os.environ.get("GREATOS_ALLOW_REMOTE_VISION", "true").lower() in {
        "1", "true", "yes", "on",
    }
    local_model = os.environ.get("JARVIS_VISION_LOCAL_MODEL", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        i = 1
        while True:
            k = os.environ.get(f"GROQ_API_KEY_{i}")
            if k:
                groq_key = k
                break
            if i > 5:
                break
            i += 1

    if remote_analysis_enabled and groq_key and importlib.util.find_spec("groq") is not None:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key, timeout=10.0)
            invite_systeme = (
                "Tu es Jarvis, l'assistant personnel de l'utilisateur. Tu analyses la capture d'écran autorisée. "
                "Réponds avec franchise, concision, style direct et flegme britannique. "
                "Ne commence JAMAIS par 'Sur cette image' ou 'On peut voir'. Va droit au fait."
            )
            prompt_utilisateur = question or "Que vois-tu actuellement sur mon écran ?"

            reponse = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[
                    {"role": "system", "content": invite_systeme},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_utilisateur},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                            },
                        ],
                    },
                ],
                max_tokens=300,
                temperature=0.2,
            )
            contenu = reponse.choices[0].message.content
            if contenu and contenu.strip():
                return contenu.strip()
        except Exception as e:
            logger.warning("Échec de l'analyse vision Groq (%s)", type(e).__name__)
    elif remote_analysis_enabled:
        logger.info("Analyse Groq vision indisponible : clé ou bibliothèque absente; tentative locale")

    if local_model and importlib.util.find_spec("ollama") is not None:
        try:
            import ollama
            local_response = ollama.chat(
                model=local_model,
                messages=[{
                    "role": "user",
                    "content": question or "Décris ce qui est visible à l'écran.",
                    "images": [base64.b64decode(b64_image)],
                }],
                options={"temperature": 0.2},
            )
            if isinstance(local_response, dict):
                local_content = local_response.get("message", {}).get("content", "")
            else:
                local_content = getattr(getattr(local_response, "message", None), "content", "")
            if local_content and str(local_content).strip():
                return str(local_content).strip()
        except Exception as e:
            logger.warning("Échec du repli vision Ollama (%s)", type(e).__name__)

    return (
        f"Capture écran locale réussie ({capture['resolution_source']}); "
        "l'interprétation cloud est indisponible et aucun modèle visuel local "
        "configuré n'a pu fournir de réponse."
    )
