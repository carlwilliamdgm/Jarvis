"""Module de transcription haute vitesse pour Jarvis avec repli local instantané.

Architecture résiliente :
1. Tentative ultra-rapide sur Groq Whisper Large v3 (latence ~200 ms) avec timeout strict de 2.0s et 0 retry bloquant.
2. Si le réseau est indisponible ou coupe : échec immédiat en <2s pour laisser Vosk local finaliser la transcription sans freeze.
"""

from __future__ import annotations

import io
import logging
import os
import wave
from typing import Optional

LOGGER = logging.getLogger(__name__)


def pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Convertit un flux brut PCM 16-bit mono en fichier WAV en mémoire."""
    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    wav_io.seek(0)
    return wav_io.read()


def transcrire_audio_groq(pcm_data: bytes, sample_rate: int = 16000) -> Optional[str]:
    """Transcrit l'audio via Groq Whisper sans retry bloquant (fallback instantané)."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    try:
        from groq import Groq
        # max_retries=0 et timeout=2.0s : si le réseau coupe, échec immédiat sans bloquer
        client = Groq(api_key=api_key, timeout=2.0, max_retries=0)

        wav_bytes = pcm_to_wav_bytes(pcm_data, sample_rate=sample_rate)
        audio_file = ("audio.wav", wav_bytes, "audio/wav")
        lang = os.getenv("JARVIS_VOICE_LANG", "fr").lower()

        reponse = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3",
            language=lang,
            response_format="text",
            temperature=0.0,
            prompt="Jarvis, Carl, ordinateur, code, fenêtre, exécuter",
        )

        texte = str(reponse).strip()
        if texte and len(texte) >= 2:
            LOGGER.info("[Groq Whisper] Transcription réussie : '%s'", texte)
            return texte
        return None
    except Exception as exc:
        LOGGER.debug("[Groq Whisper] Indisponible (%s) -> bascule immédiate sur Vosk local", exc)
        return None
