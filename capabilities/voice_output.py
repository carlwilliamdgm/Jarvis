"""Synthèse vocale Piper locale pour les interactions déclenchées par la voix.

Télécharger manuellement les modèles officiels Piper suivants, avec leur fichier
``.onnx.json`` adjacent, puis les placer dans ``models/piper/`` (ignoré par Git) :
- fr_FR-siwis-low.onnx (~31 Mo) : https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/low/fr_FR-siwis-low.onnx
- en_US-lessac-low.onnx (~32 Mo) : https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import unicodedata
from typing import Any

import numpy as np

from core.voice_state import VoiceState, _set_voice_state, get_voice_state


LOGGER = logging.getLogger(__name__)
STOP_COMMANDS = ("arrete jarvis", "stop jarvis", "tais toi jarvis")
_PIPER_MODELS = {
    "fr": "fr_FR-siwis-low.onnx",
    "en": "en_US-lessac-low.onnx",
}
_PIPER_LOCK = threading.Lock()
_PIPER_VOICE: Any | None = None


def _piper_language() -> str:
    return "en" if os.environ.get("JARVIS_VOICE_LANG", "fr").lower() == "en" else "fr"


def _piper_model_path(language: str) -> Path:
    return Path(__file__).resolve().parents[1] / "models" / "piper" / _PIPER_MODELS[language]


def get_piper_voice() -> Any:
    """Charge une seule fois la voix Piper locale choisie au démarrage."""
    global _PIPER_VOICE
    with _PIPER_LOCK:
        if _PIPER_VOICE is not None:
            return _PIPER_VOICE
        path = _piper_model_path(_piper_language())
        if not path.is_file() or not path.with_suffix(".onnx.json").is_file():
            raise RuntimeError(f"Modèle Piper ou configuration introuvable : {path}")
        from piper import PiperVoice

        _PIPER_VOICE = PiperVoice.load(path)
        return _PIPER_VOICE


def _is_stop_command(text: str) -> bool:
    """Reconnaît les commandes locales d'arrêt sans faire appel au pipeline."""
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(normalized.split()) in STOP_COMMANDS


def _recognizer_text(recognizer: Any, data: bytes) -> str:
    if recognizer.AcceptWaveform(data):
        return json.loads(recognizer.Result()).get("text", "")
    return json.loads(recognizer.PartialResult()).get("partial", "")


def _synthesise(voice: Any, texte: str) -> tuple[np.ndarray, int]:
    chunks = list(voice.synthesize(texte))
    if not chunks:
        raise RuntimeError("Piper n'a généré aucun audio")
    sample_rate = chunks[0].sample_rate
    if any(chunk.sample_rate != sample_rate for chunk in chunks):
        raise RuntimeError("Piper a généré des chunks avec des fréquences incompatibles")
    return np.concatenate([chunk.audio_int16_array for chunk in chunks]), sample_rate


def _lire_avec_interruption(audio: np.ndarray, sample_rate: int) -> None:
    """Joue le PCM Piper et interrompt la lecture à une commande stop locale."""
    import sounddevice as sd
    from capabilities.voice_input import SAMPLE_RATE, _new_recognizer

    recognizer = _new_recognizer()
    sd.play(audio, sample_rate, blocking=False)
    playback = sd.get_stream()
    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=1600, dtype="int16", channels=1) as stream:
        while playback.active:
            data, _overflowed = stream.read(1600)
            if _is_stop_command(_recognizer_text(recognizer, bytes(data))):
                LOGGER.info("Lecture Piper interrompue par commande utilisateur")
                sd.stop()
                _set_voice_state(VoiceState.IDLE)
                return


def parler_a_voix_haute(texte: str) -> None:
    """Lit ``texte`` avec Piper sans laisser une erreur TTS remonter au pipeline."""
    if not texte or get_voice_state() is not VoiceState.THINKING:
        return

    try:
        _set_voice_state(VoiceState.SPEAKING)
        audio, sample_rate = _synthesise(get_piper_voice(), texte)
        _lire_avec_interruption(audio, sample_rate)
        _set_voice_state(VoiceState.IDLE)
    except Exception:
        LOGGER.exception("Échec de la synthèse vocale Piper")
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)
