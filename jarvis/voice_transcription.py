"""Repli de transcription distant optionnel pour Jarvis.

Ce module est utilisé en préférence lorsque Groq est configuré. Définir
``JARVIS_USE_GROQ_WHISPER=0`` désactive cette tentative distante et force Vosk
local en premier; le timeout distant reste borné et sans retry bloquant.
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
        # Ne pas forcer des mots isolés ("Jarvis", "ordinateur") qui provoquent des
        # hallucinations sur les bruits de fond ou le souffle du micro.
        custom_prompt = os.getenv("JARVIS_WHISPER_PROMPT", "").strip() or None

        reponse = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3",
            language=lang,
            response_format="text",
            temperature=0.0,
            prompt=custom_prompt,
        )

        texte = str(reponse).strip()
        from jarvis.hallucinations import est_hallucination, nettoyer_transcription

        if est_hallucination(texte):
            LOGGER.warning("[Groq Whisper] Hallucination détectée et rejetée : '%s'", texte)
            return None

        texte_propre = nettoyer_transcription(texte)
        if not texte_propre or len(texte_propre) < 2:
            LOGGER.debug("[Groq Whisper] Énoncé vide ou résidu seul après nettoyage ('%s') -> ignoré", texte)
            return None

        LOGGER.info("[Groq Whisper] Transcription validée : '%s' (brut: '%s')", texte_propre, texte)
        return texte_propre
    except Exception as exc:
        LOGGER.debug("[Groq Whisper] Indisponible (%s) -> bascule immédiate sur Vosk local", exc)
        return None
