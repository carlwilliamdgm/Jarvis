"""Module de Vision d'écran pour Jarvis (GreatOS).

Permet à Jarvis d'analyser ce qui est affiché sur l'écran de l'utilisateur :
- Code source dans l'IDE (VS Code, etc.)
- Erreurs et exceptions dans le terminal
- Pages web, documents, graphiques
- Tout problème affiché à l'écran

Utilise la capture instantanée ultra-légère MSS et le modèle vision Qwen 3.8 27B sur Groq.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Optional

from PIL import Image

LOGGER = logging.getLogger(__name__)


def capturer_ecran_base64(max_width: int = 1280, qualite: int = 80) -> Optional[str]:
    """Capture l'écran complet et renvoie le flux JPEG encodé en base64."""
    img: Optional[Image.Image] = None

    # 1. Tentative rapide via MSS
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
    except Exception as mss_err:
        LOGGER.debug("[ScreenVision] MSS indisponible (%s), repli sur ImageGrab...", mss_err)

    # 2. Fallback robuste via PIL.ImageGrab
    if img is None:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
            if img:
                img = img.convert("RGB")
        except Exception as grab_err:
            LOGGER.exception("[ScreenVision] ImageGrab a également échoué : %s", grab_err)
            return None

    if img is None:
        return None

    try:
        # Redimensionner pour limiter la taille du payload
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        # Compression JPEG en mémoire
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=qualite, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        LOGGER.exception("[ScreenVision] Erreur encodage image : %s", exc)
        return None


def analyser_ecran_actuel(question: str = "Qu'y a-t-il sur mon écran ?") -> str:
    """Capture l'écran et produit une analyse concise et intelligente adaptée à Jarvis."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "Clé API Groq non configurée pour la vision, monsieur."

    image_b64 = capturer_ecran_base64()
    if not image_b64:
        return "Impossible de capturer l'affichage pour le moment, monsieur."

    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        prompt_systeme = (
            "Tu es J.A.R.V.I.S., l'assistant personnel de l'utilisateur. Tu analyses la capture d'écran autorisée.\n"
            "RÈGLES ABSOLUES :\n"
            "1. Sois direct, concis et utile (style Stark : 1 à 3 phrases percutantes).\n"
            "2. Si tu vois du code ou une erreur de compilation/terminal, identifie la cause exacte et donne la solution tout de suite.\n"
            "3. Pas de salutations inutiles, va droit au but avec élégance et précision."
        )

        res = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{prompt_systeme}\n\nQuestion de l'utilisateur : {question}"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            max_tokens=250,
            temperature=0.2,
        )

        reponse = res.choices[0].message.content.strip()
        return reponse
    except Exception as exc:
        LOGGER.exception("[ScreenVision] Erreur analyse vision : %s", exc)
        return f"Je rencontre une difficulté à interpréter le flux vidéo, monsieur. ({exc})"
