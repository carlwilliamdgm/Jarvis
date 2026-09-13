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

from jarvis.voice_state import VoiceState, _set_voice_state, get_voice_state


LOGGER = logging.getLogger(__name__)
STOP_COMMANDS = (
    "arrete jarvis",
    "stop jarvis",
    "tais toi jarvis",
    "jarvis stop",
    "jarvis arrete",
    "jarvis tais toi",
    "arrete",
    "stop",
    "tais toi",
    "silence",
    "chut",
)
_PIPER_MODELS = {
    "fr": "fr_FR-siwis-low.onnx",
    "en": "en_US-lessac-low.onnx",
}
_PIPER_LOCK = threading.Lock()
_PIPER_VOICE: Any | None = None
_TTS_STOP_EVENT = threading.Event()


def demander_arret_tts() -> None:
    """Signalé par le listener unique lorsqu'une commande locale d'arrêt est entendue."""
    _TTS_STOP_EVENT.set()


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
    cleaned = " ".join(normalized.split())
    return cleaned in STOP_COMMANDS


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
    """Joue le PCM Piper via sounddevice et interrompt sur commande stop locale.

    Pendant la lecture :
    - Le moteur audio passe en mode SPEAKING (seule la queue stop est alimentée).
    - On lit les trames de la queue stop pour détecter la commande vocale d'arrêt.
    - Après la lecture (interrompue ou naturelle), on revient en NORMAL et on
      applique la garde anti-écho (450 ms) pour éliminer la résonance des haut-parleurs.
    """
    import sounddevice as sd
    from jarvis.audio_capture import get_audio_capture_engine, CaptureMode
    from jarvis.voice_input import _new_recognizer

    engine = get_audio_capture_engine()
    recognizer = None
    try:
        recognizer = _new_recognizer()
        LOGGER.debug("Reconnaissance d'interruption activée")
    except Exception as exc:
        LOGGER.debug("Reconnaissance d'interruption indisponible: %s", exc)

    # Passer en mode SPEAKING : seule la queue stop est alimentée
    engine.set_mode(CaptureMode.SPEAKING)

    try:
        sd.play(audio, sample_rate, blocking=False)
        LOGGER.debug("Lecture audio démarrée")
    except Exception:
        LOGGER.exception("Erreur lors de la lecture audio")
        engine.set_mode(CaptureMode.NORMAL)
        engine.drainer_et_ignorer_garde(450)
        _revenir_en_ecoute()
        return

    interrupted = False
    try:
        while True:
            if _TTS_STOP_EVENT.is_set():
                LOGGER.info("Lecture Piper interrompue par événement stop")
                sd.stop()
                interrupted = True
                break
            playback = sd.get_stream()
            if playback is None or not getattr(playback, "active", False):
                LOGGER.debug("Lecture terminée naturellement")
                break
            frame = engine.lire_depuis_queue("stop", timeout=0.05)
            if frame is None:
                continue
            if recognizer is not None:
                raw = bytes(frame.samples)
                text = _recognizer_text(recognizer, raw)
                if text and _is_stop_command(text):
                    LOGGER.info("Lecture Piper interrompue par commande: '%s'", text)
                    sd.stop()
                    interrupted = True
                    break
    except Exception as exc:
        LOGGER.debug("Fin du flux d'écoute pour interruption TTS: %s", exc)
    finally:
        _TTS_STOP_EVENT.clear()
        # Attendre la fin propre si pas interrompu
        try:
            playback = sd.get_stream()
            if playback is not None and getattr(playback, "active", False):
                sd.wait()
        except Exception:
            pass
        # Revenir en mode normal + garde anti-écho post-haut-parleur
        engine.set_mode(CaptureMode.NORMAL)
        engine.drainer_et_ignorer_garde(450)
        LOGGER.debug("Fin de _lire_avec_interruption")
        _revenir_en_ecoute()
        if interrupted:
            LOGGER.info("Lecture interrompue - retour en écoute")
        else:
            LOGGER.info("Parole terminée - début écoute 30s")

def _nettoyer_markdown(texte: str) -> str:
    """Nettoie le texte pour la synthèse vocale en supprimant le markdown."""
    import re
    # Supprimer les caractères markdown courants
    texte = re.sub(r'\*+', '', texte)  # Supprimer ** et *
    texte = re.sub(r'_+', '', texte)   # Supprimer __ et _
    texte = re.sub(r'#+', '', texte)   # Supprimer #
    texte = re.sub(r'`+', '', texte)   # Supprimer ` et ```
    texte = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', texte)  # Remplacer [text](url) par text
    texte = re.sub(r'\[([^\]]+)\]', r'\1', texte)  # Remplacer [text] par text
    texte = re.sub(r'\s+', ' ', texte)  # Nettoyer les espaces multiples
    return texte.strip()


def _revenir_en_ecoute() -> None:
    """Parole/réflexion terminée → nouvelle fenêtre d'écoute 30s."""
    from jarvis.voice_input import reset_listening_timer

    reset_listening_timer()
    _set_voice_state(VoiceState.LISTENING)


def parler_a_voix_haute(texte: str) -> None:
    """Lit ``texte`` avec Piper sans laisser une erreur TTS remonter au pipeline."""
    LOGGER.info(f"parler_a_voix_haute appelé avec texte: '{texte}', état actuel: {get_voice_state()}")

    if not texte and get_voice_state() in (VoiceState.THINKING, VoiceState.ACTION):
        LOGGER.info("Texte vide - transition directe vers LISTENING")
        _revenir_en_ecoute()
        return

    if get_voice_state() not in (VoiceState.THINKING, VoiceState.ACTION):
        LOGGER.warning(f"parler_a_voix_haute ignoré - mauvais état: {get_voice_state()}")
        if get_voice_state() is not VoiceState.IDLE:
            _revenir_en_ecoute()
        return

    try:
        texte_nettoye = _nettoyer_markdown(texte)
        LOGGER.info(f"Texte nettoyé: '{texte_nettoye}'")

        LOGGER.info("Transition THINKING -> SPEAKING")
        _set_voice_state(VoiceState.SPEAKING)
        audio, sample_rate = _synthesise(get_piper_voice(), texte_nettoye)
        LOGGER.info("Audio synthétisé, début lecture")
        _lire_avec_interruption(audio, sample_rate)
        if get_voice_state() is VoiceState.SPEAKING:
            _revenir_en_ecoute()
        LOGGER.info("Lecture terminée")
    except Exception:
        LOGGER.exception("Échec de la synthèse vocale Piper")
        _set_voice_state(VoiceState.ERROR)
        _revenir_en_ecoute()
