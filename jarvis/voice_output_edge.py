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
def interrompre_lecture(stop_event: threading.Event) -> None:
    """Set the stop flag, then purge Windows playback after any in-flight start."""
    stop_event.set()
    try:
        from jarvis.voice_output import _TTS_PLAYBACK_LOCK
        import winsound
        with _TTS_PLAYBACK_LOCK:
            winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        LOGGER.debug("Windows playback purge unavailable", exc_info=True)


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


async def _generer_audio_edge(
    texte: str, voix: str, output_path: str, stop_event: threading.Event | None = None,
) -> bool:
    """Génère le flux audio via Edge-TTS avec un timeout strict de 2.5 secondes."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(texte, voix)
        generation = asyncio.create_task(communicate.save(output_path))
        if stop_event is None:
            await asyncio.wait_for(generation, timeout=2.5)
        else:
            stopped = asyncio.create_task(asyncio.to_thread(stop_event.wait))
            done, _ = await asyncio.wait(
                {generation, stopped}, timeout=2.5, return_when=asyncio.FIRST_COMPLETED,
            )
            if stopped in done and stop_event.is_set():
                generation.cancel()
                await asyncio.gather(generation, return_exceptions=True)
                return False
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)
            if generation not in done:
                generation.cancel()
                await asyncio.gather(generation, return_exceptions=True)
                raise asyncio.TimeoutError
        return True
    except Exception as exc:
        LOGGER.info("[Edge-TTS] Réseau indisponible ou lent (%s) -> bascule Piper local", exc)
        return False


def _jouer_mp3_winsound(
    chemin_mp3: str,
    stop_event: threading.Event | None = None,
    session_generation: int | None = None,
) -> bool:
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

        pcm_wav = wav_io.getvalue()
        wav_io.seek(0)
        with wave.open(wav_io, "rb") as wav_file:
            duration = wav_file.getnframes() / max(1, wav_file.getframerate())
        # Async playback permits the Windows session lock to purge audio that
        # may contain profile data; PlaySound's synchronous mode cannot be
        # interrupted reliably by the lock-monitor thread.
        from jarvis.voice_output import (
            _TTS_PLAYBACK_LOCK, _profile_is_locked, _session_generation,
        )
        with _TTS_PLAYBACK_LOCK:
            if (
                (stop_event is not None and stop_event.is_set())
                or _profile_is_locked()
                or (session_generation is not None and _session_generation() != session_generation)
            ):
                return True
            winsound.PlaySound(pcm_wav, winsound.SND_MEMORY | winsound.SND_ASYNC)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                winsound.PlaySound(None, winsound.SND_PURGE)
                return True
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return True
    except Exception as exc:
        LOGGER.warning("[winsound] Erreur lecture : %s", exc)
        return False


def _jouer_piper_local(texte: str, session_generation: int | None = None) -> None:
    """Fallback local officiel : utilise le moteur Piper local de production."""
    try:
        from jarvis.voice_output import get_piper_voice, _synthesise, _lire_avec_interruption
        LOGGER.info("[Fallback] Synthèse via Piper local officiel...")
        audio, sample_rate = _synthesise(get_piper_voice(), texte)
        _lire_avec_interruption(audio, sample_rate, session_generation=session_generation)
    except Exception as exc:
        LOGGER.exception("[Fallback] Échec Piper local : %s", exc)


def synthetiser_et_jouer(
    texte: str,
    voix: Optional[str] = None,
    stop_event: threading.Event | None = None,
    session_generation: int | None = None,
) -> bool:
    """Synthèse vocale avec bascule automatique et instantanée sur Piper local si le réseau flanche."""
    texte_propre = _nettoyer_texte(texte)
    if not texte_propre:
        return False
    if stop_event is not None and stop_event.is_set():
        return True

    lang = os.getenv("JARVIS_VOICE_LANG", "fr").lower()
    nom_voix = voix or (VOIX_DEFAUT_EN if lang == "en" else VOIX_DEFAUT_FR)

    with _TTS_LOCK:
        cache_dir = Path(__file__).resolve().parent.parent / "runtime" / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_file = str(cache_dir / f"tts_{int(time.time()*1000)}.mp3")

        succes_online = False
        try:
            # 1. Tentative Edge-TTS en ligne (< 2.5s)
            succes_online = asyncio.run(
                _generer_audio_edge(texte_propre, nom_voix, temp_file, stop_event)
            )
            if stop_event is not None and stop_event.is_set():
                return True
            if succes_online and os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                if stop_event is not None and stop_event.is_set():
                    return True
                if _jouer_mp3_winsound(temp_file, stop_event, session_generation):
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
        if stop_event is None or not stop_event.is_set():
            _jouer_piper_local(texte_propre, session_generation=session_generation)
        return True
