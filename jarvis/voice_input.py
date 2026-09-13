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
import random
import threading
import time
from typing import Any

import numpy as np

from jarvis.voice_state import VoiceState, _set_voice_state, _set_voice_transcript, get_voice_state

# Cache pour les phrases de réveil pré-synthétisées
_WAKE_PHRASES = [
    "Sir, je vous écoute",
    "À votre service",
    "Je suis là",
    "Oui, je vous écoute",
    "Que puis-je faire pour vous ?",
    "Prêt à vous aider",
    "Comment puis-je vous assister ?",
    "À vos ordres",
]
_WAKE_PHRASES_CACHE: dict[str, tuple[np.ndarray, int]] = {}
_WAKE_PHRASES_LOCK = threading.Lock()
_WAKE_VOICE_LOADED = False


def _charger_wake_voice_en_arriere_plan() -> None:
    """Charge le modèle Piper et pré-synthétise les phrases en arrière-plan."""
    global _WAKE_VOICE_LOADED
    try:
        from piper import PiperVoice
        from pathlib import Path

        language = "en" if os.environ.get("JARVIS_VOICE_LANG", "fr").lower() == "en" else "fr"
        model_names = {
            "fr": "fr_FR-siwis-low.onnx",
            "en": "en_US-lessac-low.onnx",
        }
        model_path = Path(__file__).resolve().parents[1] / "models" / "piper" / model_names[language]

        if not model_path.is_file():
            LOGGER.warning(f"Modèle Piper introuvable: {model_path}")
            return

        voice = PiperVoice.load(model_path)

        # Pré-synthétiser toutes les phrases
        with _WAKE_PHRASES_LOCK:
            for phrase in _WAKE_PHRASES:
                chunks = list(voice.synthesize(phrase))
                if chunks:
                    sample_rate = chunks[0].sample_rate
                    audio = np.concatenate([chunk.audio_int16_array for chunk in chunks])
                    _WAKE_PHRASES_CACHE[phrase] = (audio, sample_rate)

        _WAKE_VOICE_LOADED = True
        LOGGER.info(f"Voix Piper et {_WAKE_PHRASES_CACHE.__len__()} phrases pré-chargées")
    except Exception:
        LOGGER.exception("Échec du pré-chargement des phrases de réveil")


def _jouer_phrase_reveil() -> None:
    """Joue une phrase de réveil quand Jarvis est activé."""
    try:
        # Choisir une phrase aléatoire
        phrase = random.choice(_WAKE_PHRASES)
        LOGGER.info(f"Jarvis réveillé: {phrase}")

        # Récupérer l'audio depuis le cache ou le générer à la volée
        audio = None
        sample_rate = None

        with _WAKE_PHRASES_LOCK:
            if phrase in _WAKE_PHRASES_CACHE:
                audio, sample_rate = _WAKE_PHRASES_CACHE[phrase]

        if audio is None:
            # Fallback : générer à la volée si le cache n'est pas prêt
            from piper import PiperVoice
            from pathlib import Path

            language = "en" if os.environ.get("JARVIS_VOICE_LANG", "fr").lower() == "en" else "fr"
            model_names = {
                "fr": "fr_FR-siwis-low.onnx",
                "en": "en_US-lessac-low.onnx",
            }
            model_path = Path(__file__).resolve().parents[1] / "models" / "piper" / model_names[language]

            if not model_path.is_file():
                LOGGER.warning(f"Modèle Piper introuvable: {model_path}")
                return

            voice = PiperVoice.load(model_path)
            chunks = list(voice.synthesize(phrase))
            if not chunks:
                LOGGER.warning("Piper n'a généré aucun audio pour la phrase de réveil")
                return

            sample_rate = chunks[0].sample_rate
            audio = np.concatenate([chunk.audio_int16_array for chunk in chunks])

        # Lecture bloquante : l'overlay (autre process) reste sur RÉVEIL
        # pendant toute la phrase, voix et visuel sont simultanés.
        import sounddevice as sd
        sd.play(audio, sample_rate, blocking=True)

        LOGGER.info("Phrase de réveil terminée")
    except Exception:
        LOGGER.exception("Échec de la phrase de réveil")


LOGGER = logging.getLogger(__name__)
SAMPLE_RATE = 16_000
WAKE_WORD_FRAME_LENGTH = 1_280
# Seuil conservateur utilisé sans calibration locale ; configurable au démarrage.
DEFAULT_WAKE_WORD_DETECTION_THRESHOLD = 0.5
WAKE_WORD_DETECTION_THRESHOLD = DEFAULT_WAKE_WORD_DETECTION_THRESHOLD
TRANSCRIPTION_TIMEOUT_SECONDS = 8.0
SILENCE_TIMEOUT_SECONDS = 0.6
SPEECH_AMPLITUDE_THRESHOLD = 1_200
_MODEL_NAMES = {
    "fr": "vosk-model-small-fr-0.22",
    "en": "vosk-model-small-en-us-0.15",
}
_MODEL_LOCK = threading.Lock()
_VOSK_MODEL: Any | None = None
_VOSK_MODEL_LANGUAGE: str | None = None
_STOP_EVENT = threading.Event()
_LISTENER_THREAD: threading.Thread | None = None
_LISTENING_TIMEOUT_START: float | None = None
_LISTENING_TIMEOUT_SECONDS = 30.0  # Timeout avant repasser en IDLE


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


def transcrire_flux(audio_stream: Any, initial_pcm: bytes | None = None) -> str | None:
    """Transcrit un flux sounddevice avec latence minimale jusqu'au silence post-parole.

    ``initial_pcm`` réinjecte la trame qui a déclenché la VAD, pour ne pas
    perdre le début de l'énoncé.
    """
    try:
        recognizer = _new_recognizer()
        started_at = time.monotonic()
        last_speech_at = started_at
        last_partial = ""
        had_speech = False
        fragments: list[str] = []
        pending = [initial_pcm] if initial_pcm else []
        while time.monotonic() - started_at < TRANSCRIPTION_TIMEOUT_SECONDS:
            if pending:
                raw = pending.pop(0)
            else:
                data, _overflowed = audio_stream.read(WAKE_WORD_FRAME_LENGTH)
                raw = bytes(data)
            if recognizer.AcceptWaveform(raw):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    fragments.append(text)
                    had_speech = True
                    last_speech_at = time.monotonic()
                    last_partial = ""
                    _set_voice_transcript(" ".join(fragments))
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if partial:
                    had_speech = True
                    if partial != last_partial:
                        last_partial = partial
                        last_speech_at = time.monotonic()
                        prefix = " ".join(fragments)
                        _set_voice_transcript(f"{prefix} {partial}".strip())

            # Dès que la parole a été détectée et suivie du silence requis : sortie immédiate
            if had_speech and (time.monotonic() - last_speech_at >= SILENCE_TIMEOUT_SECONDS):
                break

            # Si aucune parole n'est apparue après 2.5s : sortie rapide sans attendre les 8s
            if not had_speech and (time.monotonic() - started_at >= 2.5):
                break

            # Sortie de secours si la fenêtre d'écoute globale de 30s a expiré
            # (évite que la musique ou le bruit ambiant bloque la boucle indéfiniment)
            if _fenetre_ecoute_expiree():
                LOGGER.info("Timeout fenêtre 30s atteint dans transcrire_flux — sortie forcée")
                break

        final_text = json.loads(recognizer.FinalResult()).get("text", "").strip()
        if final_text:
            fragments.append(final_text)
        result = " ".join(fragments).strip() or None
        if result:
            _set_voice_transcript(result)
        return result
    except Exception:
        LOGGER.exception("Échec de transcription Vosk (stream mort ou micro débranché)")
        # Ne pas réarmer le timer : laisser le timeout 30s expirer naturellement
        return None


def _creer_contexte_pipeline() -> tuple[list, dict]:
    """Construit le même contexte initial que la boucle CLI, au premier usage."""
    import jarvis
    from core_intellect.prompt import construire_prompt_action

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
            _set_voice_state(VoiceState.LISTENING)
            return False

        # THINKING → SPEAKING → LISTENING est géré par voice_output (thread TTS).
        return True
    except Exception:
        LOGGER.exception("Échec du pipeline déclenché par la voix")
        _set_voice_state(VoiceState.ERROR)
        reset_listening_timer()
        _set_voice_state(VoiceState.LISTENING)
        return False


def transcrire_et_soumettre(audio_stream: Any, initial_pcm: bytes | None = None) -> str | None:
    """Chemin STT partagé par le wake word et le double-clap.

    Reste en LISTENING pendant la transcription ; passe en THINKING seulement
    lorsqu'un énoncé est soumis au pipeline.
    """
    text = transcrire_flux(audio_stream, initial_pcm=initial_pcm)
    if not text:
        LOGGER.info("Aucun énoncé transcrit — reste en écoute")
        return None
    _soumettre_au_pipeline(text)
    return text


def _new_wake_word_model() -> Any:
    """Construit le détecteur local ``hey_jarvis`` avec le runtime ONNX Windows."""
    from openwakeword.model import Model

    return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")


def get_input_device() -> int | None:
    """Retourne l'identifiant du périphérique d'entrée audio (ou None pour le défaut système)."""
    configured = os.environ.get("JARVIS_AUDIO_INPUT_DEVICE") or os.environ.get("JARVIS_MICROPHONE_DEVICE")
    if configured is not None:
        try:
            return int(configured)
        except ValueError:
            LOGGER.warning("Périphérique microphone invalide (%s) ; utilisation du défaut système", configured)
    try:
        import sounddevice as sd
        default_dev = sd.default.device
        if isinstance(default_dev, (list, tuple)) and len(default_dev) > 0:
            default_in = default_dev[0]
            if default_in is not None and default_in >= 0:
                return int(default_in)
        elif isinstance(default_dev, int) and default_dev >= 0:
            return int(default_dev)
    except Exception:
        pass
    return None


def _vider_tampon_entree(stream: Any, frames: int = 3) -> None:
    """Jette toutes les trames accumulées dans le buffer pour éliminer l'écho."""
    try:
        read_avail = getattr(stream, "read_available", 0)
        while read_avail > 0:
            to_read = min(read_avail, WAKE_WORD_FRAME_LENGTH)
            stream.read(to_read)
            read_avail = getattr(stream, "read_available", 0)
    except Exception:
        pass
    for _ in range(frames):
        try:
            stream.read(WAKE_WORD_FRAME_LENGTH)
        except Exception:
            return


def _demarrer_fenetre_ecoute(stream: Any | None = None) -> None:
    """Passe en LISTENING et arme le délai de 30s."""
    global _LISTENING_TIMEOUT_START
    if stream is not None:
        _vider_tampon_entree(stream)
    _LISTENING_TIMEOUT_START = time.monotonic()
    _set_voice_transcript("")
    _set_voice_state(VoiceState.LISTENING)
    LOGGER.info("Fenêtre d'écoute 30s ouverte")


def _fenetre_ecoute_expiree() -> bool:
    """True seulement en LISTENING après 30s sans énoncé soumis."""
    if get_voice_state() is not VoiceState.LISTENING:
        return False
    if _LISTENING_TIMEOUT_START is None:
        return False
    return time.monotonic() - _LISTENING_TIMEOUT_START > _LISTENING_TIMEOUT_SECONDS


def écouter_et_transcrire() -> str | None:
    """Boucle principale d'écoute vocale avec cycle complet d'états."""
    try:
        import sounddevice as sd
        model = _new_wake_word_model()
    except ImportError:
        LOGGER.warning("Dépendances de l'écoute vocale indisponibles - mode vocal désactivé")
        time.sleep(5)
        return None

    last_submitted: str | None = None
    device_in = get_input_device()
    try:
        stream_ctx = sd.RawInputStream(
            device=device_in, samplerate=SAMPLE_RATE,
            blocksize=WAKE_WORD_FRAME_LENGTH, dtype="int16", channels=1
        )
    except Exception:
        LOGGER.warning("Impossible d'ouvrir le flux audio (micro indisponible) — retry dans 3s")
        _set_voice_state(VoiceState.IDLE)
        time.sleep(3)
        return last_submitted

    try:
        with stream_ctx as stream:
            global _LISTENING_TIMEOUT_START
            previous_state = get_voice_state()
            # Si au démarrage l'état est déjà LISTENING (crash précédent), armer le timer
            if previous_state is VoiceState.LISTENING and _LISTENING_TIMEOUT_START is None:
                _LISTENING_TIMEOUT_START = time.monotonic()
            while not _STOP_EVENT.is_set():
                pcm, _overflowed = stream.read(WAKE_WORD_FRAME_LENGTH)
                raw = bytes(pcm)
                samples = np.frombuffer(raw, dtype=np.int16)
                current_state = get_voice_state()
                entered_listening = (
                    current_state is VoiceState.LISTENING
                    and previous_state is not VoiceState.LISTENING
                    and previous_state is not VoiceState.WAKING_UP
                )
                previous_state = current_state
                if entered_listening:
                    _demarrer_fenetre_ecoute(stream)
                    continue

                if _fenetre_ecoute_expiree():
                    LOGGER.info("Timeout écoute 30s - repasse en IDLE")
                    reset_listening_timer()
                    _set_voice_state(VoiceState.IDLE)
                    previous_state = VoiceState.IDLE
                    continue

                if current_state is VoiceState.IDLE:
                    scores = model.predict(samples)
                    if scores.get("hey_jarvis", 0.0) >= WAKE_WORD_DETECTION_THRESHOLD:
                        _set_voice_state(VoiceState.WAKING_UP)
                        _jouer_phrase_reveil()
                        _demarrer_fenetre_ecoute(stream)
                        previous_state = VoiceState.LISTENING
                        continue

                elif current_state is VoiceState.LISTENING:
                    if _LISTENING_TIMEOUT_START is None:
                        _demarrer_fenetre_ecoute()

                    amplitude = int(np.max(np.abs(samples))) if samples.size else 0
                    if amplitude > SPEECH_AMPLITUDE_THRESHOLD:
                        LOGGER.info("Parole détectée")
                        submitted = transcrire_et_soumettre(stream, initial_pcm=raw)
                        if submitted:
                            last_submitted = submitted
                            previous_state = get_voice_state()
                        continue

    except Exception:
        LOGGER.exception("Échec de l'écoute wake word")
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)
        time.sleep(2)
    return last_submitted


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
    
    threading.Thread(target=_charger_wake_voice_en_arriere_plan, name="jarvis-wake-voice-loader", daemon=True).start()

    def _charger_vosk() -> None:
        try:
            get_vosk_model()
        except Exception:
            LOGGER.exception("Préchargement Vosk impossible")

    threading.Thread(target=_charger_vosk, name="jarvis-vosk-loader", daemon=True).start()
    
    _LISTENER_THREAD = threading.Thread(target=_listener_loop, name="jarvis-wake-word", daemon=True)
    _LISTENER_THREAD.start()


def reset_listening_timer() -> None:
    """Invalide la fenêtre 30s ; le prochain passage en LISTENING en ouvre une nouvelle."""
    global _LISTENING_TIMEOUT_START
    _LISTENING_TIMEOUT_START = None
    LOGGER.info("Timer écoute invalidé pour le prochain cycle 30s")


def arreter_ecoute_vocale() -> None:
    """Demande l'arrêt du listener et attend sa fin brièvement."""
    global _LISTENING_TIMEOUT_START
    _LISTENING_TIMEOUT_START = None
    _STOP_EVENT.set()
    _set_voice_state(VoiceState.IDLE)  # Force reset to IDLE on stop
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        _LISTENER_THREAD.join(timeout=2)
