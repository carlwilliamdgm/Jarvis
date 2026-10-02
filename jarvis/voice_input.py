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
import queue
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

        try:
            from jarvis.audio_capture import get_audio_capture_engine
            get_audio_capture_engine().drainer_et_ignorer_garde(350)
        except Exception:
            pass

        LOGGER.info("Phrase de réveil terminée")
    except Exception:
        LOGGER.exception("Échec de la phrase de réveil")


LOGGER = logging.getLogger(__name__)
SAMPLE_RATE = 16_000
WAKE_WORD_FRAME_LENGTH = 1_280
# Seuil conservateur utilisé sans calibration locale ; configurable au démarrage.
DEFAULT_WAKE_WORD_DETECTION_THRESHOLD = 0.5
WAKE_WORD_DETECTION_THRESHOLD = DEFAULT_WAKE_WORD_DETECTION_THRESHOLD
TRANSCRIPTION_TIMEOUT_SECONDS = 6.0  # Réduit de 8s à 6s pour réactivité améliorée
SILENCE_TIMEOUT_SECONDS = 0.6  # Réduit de 0.8s à 0.6s pour réactivité maximale

# ── ADAPTIVE WAKE WORD THRESHOLD (réduction des faux positifs) ──────────────────
_ADAPTIVE_THRESHOLD_ENABLED = True
_ADAPTIVE_THRESHOLD_WINDOW = 20  # Nombre de détections pour l'adaptation
_ADAPTIVE_THRESHOLD_HISTORY: list[float] = []  # Historique des scores récents
_ADAPTIVE_THRESHOLD_LOCK = threading.Lock()
_ADAPTIVE_THRESHOLD_MIN = 0.3  # Seuil minimum dynamique
_ADAPTIVE_THRESHOLD_MAX = 0.8  # Seuil maximum dynamique
_ADAPTIVE_THRESHOLD_ALPHA = 0.1  # Facteur d'ajustement
# ────────────────────────────────────────────────────────────────────────────────

# ── VALIDATION SECONDAIRE DU WAKE WORD (réduction drastique des faux positifs) ──
_WAKE_CONFIRMATION_ENABLED = True
_WAKE_CONFIRMATION_WINDOW = 1.5  # Fenêtre en secondes pour la confirmation
_WAKE_CONFIRMATION_DETECTIONS = 2  # Nombre de détections requises dans la fenêtre
_WAKE_CONFIRMATION_MIN_INTERVAL = 0.25  # Évite de compter deux trames voisines comme deux détections
_WAKE_DETECTION_TIMES: list[float] = []  # Timestamps des détections récentes
_WAKE_CONFIRMATION_LOCK = threading.Lock()
# ────────────────────────────────────────────────────────────────────────────────
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
_LISTENING_TIMEOUT_SECONDS = 25.0  # Réduit de 30s à 25s pour réactivité améliorée


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


def _get_adaptive_threshold() -> float:
    """Retourne le seuil adaptatif actuel pour le wake word."""
    global WAKE_WORD_DETECTION_THRESHOLD
    if not _ADAPTIVE_THRESHOLD_ENABLED:
        return WAKE_WORD_DETECTION_THRESHOLD
    with _ADAPTIVE_THRESHOLD_LOCK:
        return WAKE_WORD_DETECTION_THRESHOLD


def _update_adaptive_threshold(score: float, was_accepted: bool) -> None:
    """Met à jour le seuil adaptatif basé sur les scores récents.

    Si une détection est acceptée mais avec un score faible, on augmente le seuil.
    Si les scores sont toujours élevés mais rejetés, on baisse le seuil.
    """
    global WAKE_WORD_DETECTION_THRESHOLD, _ADAPTIVE_THRESHOLD_HISTORY
    
    if not _ADAPTIVE_THRESHOLD_ENABLED:
        return
    
    with _ADAPTIVE_THRESHOLD_LOCK:
        _ADAPTIVE_THRESHOLD_HISTORY.append(score)
        if len(_ADAPTIVE_THRESHOLD_HISTORY) > _ADAPTIVE_THRESHOLD_WINDOW:
            _ADAPTIVE_THRESHOLD_HISTORY.pop(0)
        
        # Ajustement basé sur la moyenne récente
        if len(_ADAPTIVE_THRESHOLD_HISTORY) >= 5:
            avg_score = sum(_ADAPTIVE_THRESHOLD_HISTORY) / len(_ADAPTIVE_THRESHOLD_HISTORY)
            
            if was_accepted and avg_score < WAKE_WORD_DETECTION_THRESHOLD:
                # Score accepté mais faible : augmenter le seuil pour réduire les faux positifs
                new_threshold = min(
                    _ADAPTIVE_THRESHOLD_MAX,
                    WAKE_WORD_DETECTION_THRESHOLD + _ADAPTIVE_THRESHOLD_ALPHA * (WAKE_WORD_DETECTION_THRESHOLD - avg_score)
                )
                if abs(new_threshold - WAKE_WORD_DETECTION_THRESHOLD) > 0.01:
                    LOGGER.info(
                        "Adaptive threshold: %.3f -> %.3f (avg score: %.3f, accepted)",
                        WAKE_WORD_DETECTION_THRESHOLD, new_threshold, avg_score
                    )
                    WAKE_WORD_DETECTION_THRESHOLD = new_threshold
            
            elif not was_accepted and avg_score > WAKE_WORD_DETECTION_THRESHOLD:
                # Score élevé mais rejeté : baisser le seuil pour réduire les faux négatifs
                new_threshold = max(
                    _ADAPTIVE_THRESHOLD_MIN,
                    WAKE_WORD_DETECTION_THRESHOLD - _ADAPTIVE_THRESHOLD_ALPHA * (avg_score - WAKE_WORD_DETECTION_THRESHOLD)
                )
                if abs(new_threshold - WAKE_WORD_DETECTION_THRESHOLD) > 0.01:
                    LOGGER.info(
                        "Adaptive threshold: %.3f -> %.3f (avg score: %.3f, rejected)",
                        WAKE_WORD_DETECTION_THRESHOLD, new_threshold, avg_score
                    )
                    WAKE_WORD_DETECTION_THRESHOLD = new_threshold


def _reset_adaptive_threshold() -> None:
    """Réinitialise le seuil adaptatif à sa valeur par défaut."""
    global WAKE_WORD_DETECTION_THRESHOLD, _ADAPTIVE_THRESHOLD_HISTORY
    with _ADAPTIVE_THRESHOLD_LOCK:
        WAKE_WORD_DETECTION_THRESHOLD = _load_wakeword_threshold()
        _ADAPTIVE_THRESHOLD_HISTORY.clear()
        LOGGER.info("Adaptive threshold reset to %.3f", WAKE_WORD_DETECTION_THRESHOLD)


def _confirm_wake_word(score: float) -> bool:
    """Validation secondaire : nécessite plusieurs détections dans une fenêtre courte.
    
    Réduit drastiquement les faux positifs en exigeant N détections dans une fenêtre
    temporelle courte. Évite les déclenchements sur des sons isolés ressemblant
    vaguement au wake word.
    """
    if not _WAKE_CONFIRMATION_ENABLED:
        return True
    
    global _WAKE_DETECTION_TIMES
    now = time.monotonic()
    
    with _WAKE_CONFIRMATION_LOCK:
        # Nettoyer les détections anciennes (hors fenêtre)
        _WAKE_DETECTION_TIMES = [t for t in _WAKE_DETECTION_TIMES if now - t <= _WAKE_CONFIRMATION_WINDOW]
        
        # Les trames audio arrivent toutes les ~80 ms : plusieurs scores élevés
        # consécutifs peuvent provenir du même pic et ne sont pas indépendants.
        if _WAKE_DETECTION_TIMES and now - _WAKE_DETECTION_TIMES[-1] < _WAKE_CONFIRMATION_MIN_INTERVAL:
            return False

        # Ajouter une détection suffisamment espacée
        _WAKE_DETECTION_TIMES.append(now)
        
        # Vérifier si on a suffisamment de détections dans la fenêtre
        confirmed = len(_WAKE_DETECTION_TIMES) >= _WAKE_CONFIRMATION_DETECTIONS
        
        if confirmed:
            LOGGER.info(
                "Wake word confirmé (%d détections en %.1fs, score=%.3f)",
                len(_WAKE_DETECTION_TIMES), _WAKE_CONFIRMATION_WINDOW, score
            )
            # Reset après confirmation pour éviter les réveils en cascade
            _WAKE_DETECTION_TIMES.clear()
        
        return confirmed


def _reset_wake_confirmation() -> None:
    """Réinitialise l'état de confirmation du wake word."""
    global _WAKE_DETECTION_TIMES
    with _WAKE_CONFIRMATION_LOCK:
        _WAKE_DETECTION_TIMES.clear()


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


def transcrire_flux(audio_stream: Any = None, initial_pcm: bytes | None = None) -> str | None:
    """Transcrit un flux sounddevice avec latence minimale jusqu'au silence post-parole.

    ``initial_pcm`` réinjecte la trame qui a déclenché la VAD, pour ne pas
    perdre le début de l'énoncé.
    
    Améliorations :
    - Gestion robuste des discontinuités audio
    - Timeout adaptatif basé sur la parole détectée
    - Rejet des résultats trop courts (bruit)
    """
    try:
        recognizer = _new_recognizer()
        started_at = time.monotonic()
        last_speech_at = started_at
        last_partial = ""
        had_speech = False
        fragments: list[str] = []
        has_vad = hasattr(audio_stream, "last_speech")
        pending = [initial_pcm] if initial_pcm else []
        discontinuity_count = 0
        max_discontinuities = 3  # Tolérer jusqu'à 3 discontinuités avant abandon
        
        while time.monotonic() - started_at < TRANSCRIPTION_TIMEOUT_SECONDS:
            if pending:
                raw = pending.pop(0)
                speech = bool(getattr(audio_stream, "last_speech", False))
            else:
                data, _overflowed = audio_stream.read(WAKE_WORD_FRAME_LENGTH)
                raw = bytes(data)
                speech = bool(getattr(audio_stream, "last_speech", False))
                if getattr(audio_stream, "discontinuity", False):
                    discontinuity_count += 1
                    LOGGER.warning(
                        "Trou audio pendant la transcription (%d/%d) ; poursuite avec le flux disponible",
                        discontinuity_count, max_discontinuities
                    )
                    if discontinuity_count >= max_discontinuities:
                        LOGGER.warning("Trop de discontinuités - abandon transcription")
                        break
            if speech:
                had_speech = True
                last_speech_at = time.monotonic()
            if recognizer.AcceptWaveform(raw):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    fragments.append(text)
                    last_partial = ""
                    _set_voice_transcript(" ".join(fragments))
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if partial:
                    if partial != last_partial:
                        last_partial = partial
                        # Compatibilité des sources historiques sans VAD ; le
                        # moteur unique, lui, s'appuie exclusivement sur l'énergie.
                        if not has_vad:
                            had_speech = True
                            last_speech_at = time.monotonic()
                        prefix = " ".join(fragments)
                        _set_voice_transcript(f"{prefix} {partial}".strip())

            # Dès que la parole a été détectée et suivie du silence requis : sortie immédiate
            if had_speech and (time.monotonic() - last_speech_at >= SILENCE_TIMEOUT_SECONDS):
                break

            # Si aucune parole n'est apparue après 2.0s : sortie rapide sans attendre
            if not had_speech and (time.monotonic() - started_at >= 2.0):
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
        
        # Rejeter les résultats trop courts (probablement du bruit)
        if result and len(result) < 3:
            LOGGER.debug("Transcription trop courte (%d caractères) - ignorée", len(result))
            return None
        
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




class _EngineStream:
    """Adaptateur de flux pour transcrire_flux à partir de l'AudioCaptureEngine."""

    def __init__(self, engine: Any, queue_name: str = "transcription"):
        self.engine = engine
        self.queue_name = queue_name
        self.last_speech: bool = False
        self.discontinuity: bool = False
        self.last_seq: int | None = None

    def read(self, size: int = WAKE_WORD_FRAME_LENGTH) -> tuple[bytes, bool]:
        if hasattr(self.engine, "lire_depuis_queue"):
            frame = self.engine.lire_depuis_queue(self.queue_name, timeout=0.2)
        elif hasattr(self.engine, "subscribe"):
            q = getattr(self.engine, f"_cached_{self.queue_name}_queue", None)
            if q is None:
                q = self.engine.subscribe(self.queue_name)
                setattr(self.engine, f"_cached_{self.queue_name}_queue", q)
            try:
                frame = q.get(timeout=0.2)
            except Exception:
                frame = None
        elif hasattr(self.engine, "read"):
            return self.engine.read(size)
        else:
            frame = None

        if frame is None:
            self.last_speech = False
            return bytes(np.zeros(size, dtype=np.int16)), False

        seq = getattr(frame, "seq", 0)
        if self.last_seq is not None and seq != self.last_seq + 1:
            self.discontinuity = True
        else:
            self.discontinuity = False
        self.last_seq = seq

        self.last_speech = bool(getattr(frame, "is_speech", False))
        samples = getattr(frame, "samples", frame)
        return bytes(samples), False


def _lire_trame_engine(engine: Any, queue_name: str = "wake", timeout: float = 0.1) -> Any:
    """Lit une trame depuis l'engine (supporte lire_depuis_queue et subscribe)."""
    if hasattr(engine, "lire_depuis_queue"):
        return engine.lire_depuis_queue(queue_name, timeout=timeout)
    if hasattr(engine, "subscribe"):
        q = getattr(engine, f"_cached_{queue_name}_queue", None)
        if q is None:
            q = engine.subscribe(queue_name)
            setattr(engine, f"_cached_{queue_name}_queue", q)
        try:
            return q.get(timeout=timeout)
        except Exception:
            return None
    return None


def _demarrer_fenetre_ecoute(engine=None) -> None:
    """Passe en LISTENING et arme le délai de 25s.

    Si ``engine`` est fourni, applique une courte garde anti-écho (100 ms)
    pour les transitions extérieures sans TTS préalable.
    Le drainage post-TTS (350 ms) est géré par ``_jouer_phrase_reveil``.
    """
    global _LISTENING_TIMEOUT_START
    if engine is not None and hasattr(engine, "drainer_et_ignorer_garde"):
        try:
            engine.drainer_et_ignorer_garde(100)
        except Exception:
            pass
    _LISTENING_TIMEOUT_START = time.monotonic()
    _set_voice_transcript("")
    _set_voice_state(VoiceState.LISTENING)
    LOGGER.info("Fenêtre d'écoute 25s ouverte")


def _flush_oww_state(model, n: int = 5) -> None:
    """Injecte des trames silencieuses pour réinitialiser l'état temporel d'OWW après un trou."""
    silent = np.zeros(WAKE_WORD_FRAME_LENGTH, dtype=np.int16)
    for _ in range(n):
        try:
            model.predict(silent)
        except Exception:
            break


def _fenetre_ecoute_expiree() -> bool:
    """True seulement en LISTENING après 25s sans énoncé soumis."""
    if get_voice_state() is not VoiceState.LISTENING:
        return False
    if _LISTENING_TIMEOUT_START is None:
        return False
    return time.monotonic() - _LISTENING_TIMEOUT_START > _LISTENING_TIMEOUT_SECONDS


def écouter_et_transcrire() -> str | None:
    """Boucle principale d'écoute vocale avec cycle complet d'états."""
    try:
        from jarvis.audio_capture import get_audio_capture_engine
        model = _new_wake_word_model()
    except ImportError:
        LOGGER.warning("Dépendances de l'écoute vocale indisponibles - mode vocal désactivé")
        time.sleep(5)
        return None

    last_submitted: str | None = None
    engine = get_audio_capture_engine(get_input_device())
    if not engine.ouvrir():
        LOGGER.warning("Impossible d'ouvrir le flux audio natif — retry dans 3s")
        _set_voice_state(VoiceState.IDLE)
        time.sleep(3)
        return last_submitted

    last_seq: int | None = None

    try:
        global _LISTENING_TIMEOUT_START
        previous_state = get_voice_state()
        if previous_state is VoiceState.LISTENING and _LISTENING_TIMEOUT_START is None:
            _LISTENING_TIMEOUT_START = time.monotonic()

        while not _STOP_EVENT.is_set():
            frame = _lire_trame_engine(engine, "wake", timeout=0.1)
            if frame is None:
                # Pas de trame disponible : vérifier les timeouts tout de même
                if _fenetre_ecoute_expiree():
                    LOGGER.info("Timeout écoute 25s - repasse en IDLE")
                    reset_listening_timer()
                    _set_voice_state(VoiceState.IDLE)
                continue

            # Détection de trou : flush état temporel OWW pour ne pas présenter
            # une séquence audio disjointe au modèle.
            seq = getattr(frame, "seq", 0)
            if last_seq is not None and seq != last_seq + 1:
                gap = seq - last_seq - 1
                LOGGER.warning("Trou audio wake word: %d trames — flush OWW", gap)
                _flush_oww_state(model)
            last_seq = seq

            current_state = get_voice_state()
            entered_listening = (
                current_state is VoiceState.LISTENING
                and previous_state is not VoiceState.LISTENING
                and previous_state is not VoiceState.WAKING_UP
            )
            previous_state = current_state

            if entered_listening:
                _demarrer_fenetre_ecoute(engine)
                continue

            if _fenetre_ecoute_expiree():
                LOGGER.info("Timeout écoute 25s - repasse en IDLE")
                reset_listening_timer()
                _set_voice_state(VoiceState.IDLE)
                previous_state = VoiceState.IDLE
                continue

            samples = getattr(frame, "samples", frame)
            if current_state in (VoiceState.IDLE, VoiceState.LISTENING):
                scores = model.predict(samples)
                wake_score = scores.get("hey_jarvis", 0.0)
                current_threshold = _get_adaptive_threshold()
                
                if wake_score >= current_threshold:
                    # Wake word détecté : validation secondaire
                    if _confirm_wake_word(wake_score):
                        # Confirmation réussie : mettre à jour le seuil adaptatif
                        _update_adaptive_threshold(wake_score, was_accepted=True)
                        
                        if current_state is VoiceState.IDLE:
                            _set_voice_state(VoiceState.WAKING_UP)
                            _jouer_phrase_reveil()  # inclut drainer_et_ignorer_garde(350)
                        else:
                            # Réarmement en LISTENING : pas de phrase de réveil
                            LOGGER.info("Wake word en LISTENING — réarmement 30s")
                        _demarrer_fenetre_ecoute()  # sans drain supplémentaire
                        previous_state = VoiceState.LISTENING
                        continue
                    else:
                        # Détection non confirmée : logger pour debug
                        LOGGER.debug("Wake word détecté mais non confirmé (score=%.3f)", wake_score)
                else:
                    # Score sous le seuil : mettre à jour l'historique pour l'adaptation
                    if wake_score > 0.1:  # Ignorer les scores très bas
                        _update_adaptive_threshold(wake_score, was_accepted=False)

            if current_state is VoiceState.LISTENING:
                if _LISTENING_TIMEOUT_START is None:
                    _demarrer_fenetre_ecoute(engine)
                if getattr(frame, "is_speech", False):
                    LOGGER.info("Parole détectée (VAD)")
                    submitted = transcrire_et_soumettre(_EngineStream(engine), initial_pcm=None)
                    if submitted:
                        last_submitted = submitted
                        previous_state = get_voice_state()

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
    """Démarre le listener wake word dans un thread démon, si nécessaire.
    
    Optimisations de latence :
    - Préchargement parallèle des modèles (Vosk, Piper, openWakeWord)
    - Démarrage immédiat du listener après préchargement des modèles critiques
    """
    global _LISTENER_THREAD, WAKE_WORD_DETECTION_THRESHOLD
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        return
    WAKE_WORD_DETECTION_THRESHOLD = _load_wakeword_threshold()
    _STOP_EVENT.clear()
    
    # Préchargement parallèle de tous les modèles pour latence minimale
    threading.Thread(target=_charger_wake_voice_en_arriere_plan, name="jarvis-wake-voice-loader", daemon=True).start()

    def _charger_vosk() -> None:
        try:
            get_vosk_model()
            LOGGER.info("Modèle Vosk préchargé avec succès")
        except Exception:
            LOGGER.exception("Préchargement Vosk impossible")

    def _charger_oww() -> None:
        try:
            model = _new_wake_word_model()
            LOGGER.info("Modèle openWakeWord préchargé avec succès")
        except Exception:
            LOGGER.exception("Préchargement openWakeWord impossible")

    threading.Thread(target=_charger_vosk, name="jarvis-vosk-loader", daemon=True).start()
    threading.Thread(target=_charger_oww, name="jarvis-oww-loader", daemon=True).start()
    
    _LISTENER_THREAD = threading.Thread(target=_listener_loop, name="jarvis-wake-word", daemon=True)
    _LISTENER_THREAD.start()


def reset_listening_timer() -> None:
    """Invalide la fenêtre 30s ; le prochain passage en LISTENING en ouvre une nouvelle."""
    global _LISTENING_TIMEOUT_START
    _LISTENING_TIMEOUT_START = None
    LOGGER.info("Timer écoute invalidé pour le prochain cycle 30s")


def arreter_ecoute_vocale() -> None:
    """Demande l'arrêt du listener et ferme le moteur audio."""
    global _LISTENING_TIMEOUT_START
    _LISTENING_TIMEOUT_START = None
    _STOP_EVENT.set()
    _set_voice_state(VoiceState.IDLE)
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        _LISTENER_THREAD.join(timeout=2)
    try:
        from jarvis.audio_capture import get_audio_capture_engine
        get_audio_capture_engine().fermer()
    except Exception:
        pass
