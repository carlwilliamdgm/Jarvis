"""Module de synthèse vocale hybride résilient pour Jarvis (Edge-TTS + Fallback Piper local immédiat).

Fonctionnement :
1. Tentative en ligne ultra-naturelle avec Microsoft Edge Neural TTS (Henri).
2. Si le réseau est déconnecté, lent ou échoue (timeout 2.5s) :
   -> Bascule instantanée et transparente sur Piper local officiel de production.
L'utilisateur entend TOUJOURS une réponse quoi qu'il arrive.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import threading
import time
import wave
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

VOIX_DEFAUT_FR = "fr-FR-HenriNeural"
VOIX_DEFAUT_EN = "en-US-ChristopherNeural"

_TTS_LOCK = threading.Lock()


def _nettoyer_texte(texte: Any) -> str:
    """Normalise et adoucit le texte pour une diction orale fluide et naturelle."""
    if isinstance(texte, (tuple, list)):
        texte = str(texte[0]) if texte else ""
    elif isinstance(texte, dict):
        texte = str(texte.get("reponse", texte.get("texte", "")))
    else:
        texte = str(texte or "")

    texte = texte.replace('\u202f', ' ').replace('\xa0', ' ')
    texte = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', texte)
    texte = re.sub(r'```[\s\S]*?```', '', texte)
    texte = re.sub(r'`([^`]+)`', r'\1', texte)
    texte = re.sub(r'[*_#~>]', '', texte)

    # Normalisation phonétique des heures et unités
    texte = re.sub(r'(\d{1,2})\s*h\s*(\d{1,2})', r'\1 heures \2', texte, flags=re.IGNORECASE)
    texte = re.sub(r'\b1\s*h\b', '1 heure', texte, flags=re.IGNORECASE)
    texte = re.sub(r'(\d{1,2})\s*h\b', r'\1 heures', texte, flags=re.IGNORECASE)
    texte = re.sub(r'\b1\s*min\b', '1 minute', texte, flags=re.IGNORECASE)
    texte = re.sub(r'(\d+)\s*min\b', r'\1 minutes', texte, flags=re.IGNORECASE)
    texte = re.sub(r'(\d+)\s*%', r'\1 pour cent', texte)
    texte = re.sub(r'(\d+)\s*°C', r'\1 degrés', texte)

    texte = re.sub(r'\s+', ' ', texte)
    return texte.strip()


async def _generer_audio_edge(texte: str, voix: str, output_path: str) -> bool:
    """Génère le flux audio via Edge-TTS avec un timeout strict de 2.5 secondes."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(texte, voix)
        await asyncio.wait_for(communicate.save(output_path), timeout=2.5)
        return True
    except Exception as exc:
        LOGGER.info("[Edge-TTS] Réseau indisponible ou lent (%s) -> bascule Piper local", exc)
        return False


def _jouer_mp3_winsound(chemin_mp3: str) -> bool:
    """Décode le MP3 en mémoire et le joue via winsound sans bloquer le matériel."""
    try:
        import winsound
        import miniaudio

        with open(chemin_mp3, "rb") as f:
            mp3_bytes = f.read()

        dec = miniaudio.decode(mp3_bytes)
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(dec.nchannels)
            wf.setsampwidth(2)
            wf.setframerate(dec.sample_rate)
            wf.writeframes(dec.samples)

        winsound.PlaySound(wav_io.getvalue(), winsound.SND_MEMORY)
        return True
    except Exception as exc:
        LOGGER.warning("[winsound] Erreur lecture : %s", exc)
        return False


def _jouer_piper_local(texte: str) -> None:
    """Fallback local officiel : utilise le moteur Piper local de production."""
    try:
        from jarvis.voice_output import get_piper_voice, _synthesise, _lire_avec_interruption
        LOGGER.info("[Fallback] Synthèse via Piper local officiel...")
        audio, sample_rate = _synthesise(get_piper_voice(), texte)
        _lire_avec_interruption(audio, sample_rate)
    except Exception as exc:
        LOGGER.exception("[Fallback] Échec Piper local : %s", exc)


def synthetiser_et_jouer(texte: str, voix: Optional[str] = None) -> bool:
    """Synthèse vocale avec bascule automatique et instantanée sur Piper local si le réseau flanche."""
    texte_propre = _nettoyer_texte(texte)
    if not texte_propre:
        return False

    lang = os.getenv("JARVIS_VOICE_LANG", "fr").lower()
    nom_voix = voix or (VOIX_DEFAUT_EN if lang == "en" else VOIX_DEFAUT_FR)

    with _TTS_LOCK:
        cache_dir = Path(__file__).resolve().parent.parent / "runtime" / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_file = str(cache_dir / f"tts_{int(time.time()*1000)}.mp3")

        succes_online = False
        try:
            # 1. Tentative Edge-TTS en ligne (< 2.5s)
            succes_online = asyncio.run(_generer_audio_edge(texte_propre, nom_voix, temp_file))
            if succes_online and os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                if _jouer_mp3_winsound(temp_file):
                    return True
        except Exception as exc:
            LOGGER.debug("[TTS] Exception Edge-TTS : %s", exc)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

        # 2. Si échec ou pas d'internet : repli immédiat sur Piper local officiel !
        _jouer_piper_local(texte_propre)
        return True
