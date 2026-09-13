"""Déclencheur déterministe de double-clap utilisant uniquement l'amplitude audio.

Le détecteur lit depuis la queue ``wake`` du moteur de capture unique
(``AudioCaptureEngine``) : aucun ``sd.RawInputStream`` supplémentaire
n'est ouvert — évite la contention de périphérique avec voice_input.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from jarvis.voice_input import WAKE_WORD_FRAME_LENGTH, _jouer_phrase_reveil, get_input_device, transcrire_et_soumettre
from jarvis.voice_state import VoiceState, _set_voice_state, get_voice_state


LOGGER = logging.getLogger(__name__)
# Amplitude int16 absolue minimale d'un clap.
CLAP_AMPLITUDE_THRESHOLD = 3_000
# Les deux pics doivent être espacés dans cette fenêtre (en secondes).
DOUBLE_CLAP_MIN_INTERVAL_SECONDS = 0.20
DOUBLE_CLAP_MAX_INTERVAL_SECONDS = 0.80
_STOP_EVENT = threading.Event()
_LISTENER_THREAD: threading.Thread | None = None


class DoubleClapDetector:
    """Petit automate sans ML, isolé pour permettre des tests sur signal synthétique."""

    def __init__(self) -> None:
        self._first_peak_at: float | None = None

    def process_peak(self, amplitude: int, now: float) -> bool:
        if self._first_peak_at is not None and now - self._first_peak_at > DOUBLE_CLAP_MAX_INTERVAL_SECONDS:
            self._first_peak_at = None
        if amplitude < CLAP_AMPLITUDE_THRESHOLD:
            return False
        if self._first_peak_at is None:
            self._first_peak_at = now
            return False
        interval = now - self._first_peak_at
        self._first_peak_at = None
        return DOUBLE_CLAP_MIN_INTERVAL_SECONDS <= interval <= DOUBLE_CLAP_MAX_INTERVAL_SECONDS


def _maximum_amplitude(data: bytes | np.ndarray) -> int:
    if isinstance(data, np.ndarray):
        return int(np.max(np.abs(data))) if data.size else 0
    samples = memoryview(data).cast("h")
    return max((abs(sample) for sample in samples), default=0)


def _listener_loop() -> None:
    try:
        from jarvis.audio_capture import get_audio_capture_engine
        detector = DoubleClapDetector()
        engine = get_audio_capture_engine(get_input_device())
        if not engine.ouvrir():
            LOGGER.warning("[ClapInput] Impossible d'ouvrir le moteur audio")
            return
        LOGGER.info("[ClapInput] Démarré sur queue wake du moteur unique")
        while not _STOP_EVENT.is_set():
            frame = engine.lire_depuis_queue("wake", timeout=0.1)
            if frame is None:
                continue
            if get_voice_state() is not VoiceState.IDLE:
                continue
            amplitude = int(np.max(np.abs(frame.samples))) if frame.samples.size else 0
            if not detector.process_peak(amplitude, time.monotonic()):
                continue
            _set_voice_state(VoiceState.WAKING_UP)
            _jouer_phrase_reveil()
            _set_voice_state(VoiceState.LISTENING)
            transcrire_et_soumettre(engine)
    except Exception:
        LOGGER.exception("Échec de l'écoute double-clap")
        _set_voice_state(VoiceState.ERROR)
        _set_voice_state(VoiceState.IDLE)


def demarrer_ecoute_clap() -> None:
    """Démarre le listener double-clap dans son propre thread démon."""
    global _LISTENER_THREAD
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        return
    _STOP_EVENT.clear()
    _LISTENER_THREAD = threading.Thread(target=_listener_loop, name="jarvis-double-clap", daemon=True)
    _LISTENER_THREAD.start()


def arreter_ecoute_clap() -> None:
    """Demande l'arrêt du listener double-clap et attend sa fin brièvement."""
    _STOP_EVENT.set()
    _set_voice_state(VoiceState.IDLE)
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        _LISTENER_THREAD.join(timeout=2)
