"""Déclencheur déterministe de double-clap utilisant uniquement l'amplitude audio."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from jarvis.voice_state import VoiceState, _set_voice_state
from jarvis.voice_input import SAMPLE_RATE, get_input_device, transcrire_et_soumettre


LOGGER = logging.getLogger(__name__)
# À calibrer sur le microphone réel : amplitude int16 absolue minimale d'un clap.
CLAP_AMPLITUDE_THRESHOLD = 3_000
# Les deux pics doivent être espacés de cette fenêtre (en secondes).
DOUBLE_CLAP_MIN_INTERVAL_SECONDS = 0.20
DOUBLE_CLAP_MAX_INTERVAL_SECONDS = 0.80
CLAP_BLOCK_SIZE = 800
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


def _maximum_amplitude(data: bytes) -> int:
    samples = memoryview(data).cast("h")
    return max((abs(sample) for sample in samples), default=0)


def _listener_loop() -> None:
    try:
        import sounddevice as sd
        detector = DoubleClapDetector()
        device_in = get_input_device()
        with sd.RawInputStream(device=device_in, samplerate=SAMPLE_RATE, blocksize=CLAP_BLOCK_SIZE,
                               dtype="int16", channels=1) as stream:
            while not _STOP_EVENT.is_set():
                data, _overflowed = stream.read(CLAP_BLOCK_SIZE)
                if not detector.process_peak(_maximum_amplitude(bytes(data)), time.monotonic()):
                    continue
                if not _set_voice_state(VoiceState.LISTENING):
                    continue
                transcrire_et_soumettre(stream)
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
    if _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        _LISTENER_THREAD.join(timeout=2)
