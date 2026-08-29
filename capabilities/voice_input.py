"""Wake word openWakeWord et transcription Vosk pour Jarvis.

Les modèles Vosk ne sont pas versionnés. Téléchargez-les depuis
https://alphacephei.com/vosk/models puis placez-les dans ``models/`` à la
racine du projet (ou définissez ``JARVIS_VOSK_MODELS_DIR``).

Le modèle pré-entraîné ``hey_jarvis`` est fourni par openWakeWord, mais ses
ressources ONNX doivent être téléchargées une fois pendant le déploiement via
``openwakeword.utils.download_models(["hey_jarvis"])``. La détection ne fait
aucun appel réseau au runtime.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np

from core.voice_state import VoiceState, _set_voice_state


LOGGER = logging.getLogger(__name__)
SAMPLE_RATE = 16_000
WAKE_WORD_FRAME_LENGTH = 1_280
# Seuil conservateur utilisé sans calibration locale ; configurable au démarrage.
DEFAULT_WAKE_WORD_DETECTION_THRESHOLD = 0.1
WAKE_WORD_DETECTION_THRESHOLD = DEFAULT_WAKE_WORD_DETECTION_THRESHOLD
TRANSCRIPTION_TIMEOUT_SECONDS = 8.0
SILENCE_TIMEOUT_SECONDS = 1.2
_MODEL_NAMES = {
    "fr": "vosk-model-small-fr-0.22",
    "en": "vosk-model-small-en-us-0.15",
}
_MODEL_LOCK = threading.Lock()
_VOSK_MODEL: Any | None = None
_VOSK_MODEL_LANGUAGE: str | None = None
_STOP_EVENT = threading.Event()
_LISTENER_THREAD: threading.Thread | None = None


def _language() -> str:
    return "en" if os.environ.get("JARVIS_VOICE_LANG", "fr").lower() == "en" else "fr"


def _load_wakeword_threshold() -> float:
    """Lit le seuil de détection au démarrage du listener vocal uniquement."""
    configured = os.environ.get("JARVIS_WAKEWORD_THRESHOLD")
    if configured is None:
        return DEFAULT_WAKE_WORD_DETECTION_THRESHOLD
    try:
        threshold = float(configured)
    except ValueError:
        LOGGER.warning("JARVIS_WAKEWORD_THRESHOLD invalide ; seuil 0.5 utilisé")
        return DEFAULT_WAKE_WORD_DETECTION_THRESHOLD
    # openWakeWord renvoie un score entre 0.0 et 1.0 ; toute autre valeur est invalide.
    if not 0.0 <= threshold <= 1.0:
        LOGGER.warning("JARVIS_WAKEWORD_THRESHOLD hors plage ; seuil 0.5 utilisé")
        return DEFAULT_WAKE_WORD_DETECTION_THRESHOLD
    return threshold


def _model_path(language: str) -> Path:
    root = os.environ.get("JARVIS_VOSK_MODELS_DIR")
    models_root = Path(root).expanduser() if root else Path(__file__).resolve().parents[1] / "models"
    return models_root / _MODEL_NAMES[language]


def get_vosk_model() -> Any:
    """Charge le modèle correspondant à la langue une seule fois par processus."""
    global _VOSK_MODEL, _VOSK_MODEL_LANGUAGE
    language = _language()
    with _MODEL_LOCK:
        if _VOSK_MODEL is not None:
            return _VOSK_MODEL
        try:
            from vosk import Model
        except ImportError as exc:
            raise RuntimeError("La dépendance vosk est requise pour la voix.") from exc
        path = _model_path(language)
        if not path.is_dir():
            raise RuntimeError(f"Modèle Vosk introuvable : {path}")
        _VOSK_MODEL = Model(str(path))
        _VOSK_MODEL_LANGUAGE = language
        return _VOSK_MODEL


def _new_recognizer() -> Any:
    from vosk import KaldiRecognizer
    return KaldiRecognizer(get_vosk_model(), SAMPLE_RATE)


def transcrire_flux(audio_stream: Any) -> str | None:
    """Transcrit un flux sounddevice déjà ouvert jusqu'au silence ou timeout."""
    try:
        recognizer = _new_recognizer()
        started_at = time.monotonic()
        last_speech_at = started_at
        fragments: list[str] = []
        while time.monotonic() - started_at < TRANSCRIPTION_TIMEOUT_SECONDS:
            data, _overflowed = audio_stream.read(1600)
            raw = bytes(data)
            if recognizer.AcceptWaveform(raw):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    fragments.append(text)
                    last_speech_at = time.monotonic()
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if partial:
                    last_speech_at = time.monotonic()
            if fragments and time.monotonic() - last_speech_at >= SILENCE_TIMEOUT_SECONDS:
                break
        final_text = json.loads(recognizer.FinalResult()).get("text", "").strip()
        if final_text:
            fragments.append(final_text)
        return " ".join(fragments).strip() or None
    except Exception:
        LOGGER.exception("Échec de transcription Vosk")
        return None


def _creer_contexte_pipeline() -> tuple[list, dict]:
    """Construit le même contexte initial que la boucle CLI, au premier usage."""
    import jarvis
    from core.prompt import construire_prompt_action

    memoire = jarvis.initialiser()
    return [{"role": "system", "content": construire_prompt_action(memoire)}], memoire


_pipeline_context: tuple[list, dict] | None = None
_pipeline_context_lock = threading.Lock()


def _soumettre_au_pipeline(text: str) -> bool:
    """Exécute l'interaction commune sans bloquer une occurrence vocale en attente."""
    try:
        global _pipeline_context
        with _pipeline_context_lock:
            if _pipeline_context is None:
                _pipeline_context = _creer_contexte_pipeline()
            historique, memoire = _pipeline_context
        import jarvis
        _set_voice_state(VoiceState.THINKING)
        result = jarvis.executer_interaction_utilisateur(
            text, historique, memoire, ignorer_si_occupe=True, origine_vocale=True
        )
        if result is None:
            LOGGER.info("Entrée vocale ignorée : pipeline déjà occupé")
            _set_voice_state(VoiceState.IDLE)
            return False
        return True
    except Exception:
        LOGGER.exception("Échec du pipeline déclenché par la voix")
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)
        return False


def transcrire_et_soumettre(audio_stream: Any) -> str | None:
    """Chemin STT partagé par le wake word et le double-clap."""
    text = transcrire_flux(audio_stream)
    if not text:
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)
        return None
    _soumettre_au_pipeline(text)
    return text


def _new_wake_word_model() -> Any:
    """Construit le détecteur local ``hey_jarvis`` avec le runtime ONNX Windows."""
    from openwakeword.model import Model

    return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")


def écouter_et_transcrire() -> str | None:
    """Attend un wake word puis transcrit et transmet une seule requête."""
    try:
        import sounddevice as sd
        model = _new_wake_word_model()
    except ImportError:
        LOGGER.exception("Dépendances de l'écoute vocale indisponibles")
        return None

    try:
        with sd.RawInputStream(device=1, samplerate=SAMPLE_RATE, blocksize=WAKE_WORD_FRAME_LENGTH,
                               dtype="int16", channels=1) as stream:
            while not _STOP_EVENT.is_set():
                pcm, _overflowed = stream.read(WAKE_WORD_FRAME_LENGTH)
                samples = np.frombuffer(bytes(pcm), dtype=np.int16)
                scores = model.predict(samples)
                if scores.get("hey_jarvis", 0.0) >= WAKE_WORD_DETECTION_THRESHOLD:
                    if not _set_voice_state(VoiceState.LISTENING):
                        continue
                    return transcrire_et_soumettre(stream)
    except Exception:
        LOGGER.exception("Échec de l'écoute wake word")
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)
    return None


def _listener_loop() -> None:
    while not _STOP_EVENT.is_set():
        écouter_et_transcrire()
        _STOP_EVENT.wait(0.1)


def demarrer_ecoute_vocale() -> None:
    """Démarre le listener wake word dans un thread démon, si nécessaire."""
    global _LISTENER_THREAD, WAKE_WORD_DETECTION_THRESHOLD
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        return
    WAKE_WORD_DETECTION_THRESHOLD = _load_wakeword_threshold()
    _STOP_EVENT.clear()
    _LISTENER_THREAD = threading.Thread(target=_listener_loop, name="jarvis-wake-word", daemon=True)
    _LISTENER_THREAD.start()


def arreter_ecoute_vocale() -> None:
    """Demande l'arrêt du listener et attend sa fin brièvement."""
    _STOP_EVENT.set()
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        _LISTENER_THREAD.join(timeout=2)
