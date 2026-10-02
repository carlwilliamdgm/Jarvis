"""Desktop Vision - Vision multimodale en direct du poste de travail pour GreatOS.

Permet à Jarvis de 'voir' en direct l'écran de Carl (ou la fenêtre active)
via capture d'écran Windows native à haute vitesse et analyse multimodale VLM (Groq qwen3.8-27b).
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import io
import logging
import os
from typing import Any, Dict, Optional
from PIL import Image, ImageGrab

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32


def attacher_bureau_interactif() -> bool:
    """Attache le thread courant à la station de bureau interactive Windows (winsta0\\default).

    Permet à un service ou à un processus d'arrière-plan d'accéder au vrai bureau
    graphique de l'utilisateur interactif Carl.
    """
    try:
        hwinsta = user32.OpenWindowStationW("winsta0", False, 0x037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
            hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
                return True
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
    attacher_bureau_interactif()

    boite_rognage = None
    if zone == "fenetre_active":
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                # (left, top, right, bottom)
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 20 and h > 20:
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
        return f"Impossible de capturer l'écran en direct : {e}"

    b64_image = capture["base64"]

    # Tentative avec Groq Qwen3.8-27b Multimodal
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

    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key, timeout=10.0)
            invite_systeme = (
                "Tu es Jarvis, l'IA personnelle de Carl-William. Tu regardes en direct son écran d'ordinateur. "
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
            logger.warning("Échec de l'analyse vision Groq : %s", e)

    return f"Capture d'écran effectuée ({capture['resolution_source']}), mais aucun moteur de vision multimodal n'a pu interpréter les pixels pour le moment."
