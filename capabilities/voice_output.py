"""Synthèse vocale locale pour les interactions déclenchées par la voix."""

from __future__ import annotations

import logging

from core.voice_state import VoiceState, _set_voice_state, get_voice_state


LOGGER = logging.getLogger(__name__)


def parler_a_voix_haute(texte: str) -> None:
    """Lit ``texte`` avec SAPI sans laisser une erreur TTS remonter au pipeline."""
    if not texte or get_voice_state() is not VoiceState.THINKING:
        return

    try:
        _set_voice_state(VoiceState.SPEAKING)
        import pyttsx3

        engine = pyttsx3.init()
        engine.say(texte)
        engine.runAndWait()
        _set_voice_state(VoiceState.IDLE)
    except Exception:
        LOGGER.exception("Échec de la synthèse vocale")
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)
