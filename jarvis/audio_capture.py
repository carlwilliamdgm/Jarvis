# jarvis/audio_capture.py
"""Moteur unique de capture audio (Single Audio Capture Engine) pour GreatOS.

Architecture :
- Un seul sd.RawInputStream ouvert pour toute la session.
- Thread de capture arriere-plan, accumulation, trames 16 kHz mono exactes.
- Distribution vers 3 queues bornees par consommateur : wake / transcription / stop.
- Calibration du canal micro au demarrage + hysterese (ratio 3x / 10 trames).
- Reechantillonnage polyphase a etat persistant via samplerate.Resampler.
- VAD adaptative : plancher de bruit mis a jour uniquement en periode silencieuse.
- Periode de garde anti-echo post-TTS (450 ms par defaut).
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import queue
import threading
import time
from typing import Any, Optional

import numpy as np

try:
    import samplerate as _samplerate_lib
    _HAS_SAMPLERATE = True
except ImportError:
    _samplerate_lib = None  # type: ignore[assignment]
    _HAS_SAMPLERATE = False

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000
FRAME_SIZE = 1_280  # 80 ms @ 16 kHz (openWakeWord + Vosk)
# Alias de retrocompatibilite
DEFAULT_FRAME_LENGTH = FRAME_SIZE


# ---------------------------------------------------------------------------
# Structures de donnees publiques
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AudioFrame:
    """Trame 16 kHz mono emise par le moteur de capture.

    ``seq`` est un compteur monotone : un trou (seq != last_seq + 1) signale
    une perte de donnees. Chaque consommateur doit reinitialiser son etat
    interne (OWW, Vosk) lorsqu'il detecte un trou.
    """

    seq: int
    samples: np.ndarray   # int16, shape (FRAME_SIZE,)
    is_speech: bool
    timestamp: float = 0.0


class CaptureMode(enum.Enum):
    """Mode de distribution des trames vers les queues consommateurs."""

    NORMAL   = "normal"    # Alimente wake + transcription
    SPEAKING = "speaking"  # Alimente uniquement stop_cmd (pendant TTS)
    PAUSED   = "paused"    # N'alimente aucune queue (drain materiel continue)


# ---------------------------------------------------------------------------
# VAD adaptative
# ---------------------------------------------------------------------------


class AdaptiveVAD:
    """Detecteur d'activite vocale base sur l'energie relative au plancher ambiant.

    Le plancher de bruit ne se met a jour QUE pendant les periodes silencieuses
    reconnues, pour eviter d'apprendre la voix et de remonter le seuil.
    """

    def __init__(
        self,
        alpha: float = 0.05,
        min_ratio: float = 2.2,
        min_threshold: int = 150,
    ) -> None:
        self.noise_floor = 50.0
        self.alpha = alpha
        self.min_ratio = min_ratio
        self.min_threshold = min_threshold
        self.is_speech_active = False

    def process(self, samples: np.ndarray) -> bool:
        if samples.size == 0:
            return False
        energy = float(np.max(np.abs(samples)))
        threshold = max(self.noise_floor * self.min_ratio, float(self.min_threshold))
        is_speech = energy > threshold
        # Mise a jour du plancher UNIQUEMENT en periode calme reconnue
        if not is_speech:
            self.noise_floor = (
                (1.0 - self.alpha) * self.noise_floor + self.alpha * energy
            )
        self.is_speech_active = is_speech
        return is_speech

    def reset_floor(self, default_val: float = 50.0) -> None:
        self.noise_floor = default_val


# ---------------------------------------------------------------------------
# Queues bornees par consommateur
# ---------------------------------------------------------------------------


class _DropOldestQueue:
    """Queue a remplacement glissant (politique drop-oldest).

    Utilisee pour wake et stop : la fraicheur prime sur l'exhaustivite.
    Chaque perte incremente ``drops`` et leve ``drop_event``.
    """

    def __init__(self, maxsize: int) -> None:
        self._q: queue.Queue[AudioFrame] = queue.Queue(maxsize=maxsize)
        self.drops = 0
        self._lock = threading.Lock()
        self.drop_event = threading.Event()

    def put(self, frame: AudioFrame) -> bool:
        """Insere ; si pleine, supprime la plus ancienne. Retourne True si perte."""
        try:
            self._q.put_nowait(frame)
            return False
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                pass
            with self._lock:
                self.drops += 1
            self.drop_event.set()
            return True

    def get(self, timeout: float = 0.1) -> Optional[AudioFrame]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        """Vide la queue et reinitialise l'evenement. Retourne le nombre drain."""
        drained = 0
        while True:
            try:
                self._q.get_nowait()
                drained += 1
            except queue.Empty:
                break
        self.drop_event.clear()
        return drained

    @property
    def qsize(self) -> int:
        return self._q.qsize()


class _TranscriptionQueue:
    """Queue a signal de saturation (pas de drop silencieux).

    Lorsque pleine, leve ``overflow_event`` : le consommateur Vosk doit
    detecter cet evenement, abandonner l'enonce courant et reinitialiser
    son recognizer. Taille reduite (~1.3 s) pour reveler vite les problemes
    de performance plutot que creer une latence cachee.
    """

    def __init__(self, maxsize: int = 16) -> None:
        self._q: queue.Queue[AudioFrame] = queue.Queue(maxsize=maxsize)
        self.overflow_event = threading.Event()
        self.drops = 0

    def put(self, frame: AudioFrame) -> bool:
        """Insere ; si pleine, signale la surcharge sans drop silencieux."""
        try:
            self._q.put_nowait(frame)
            return False
        except queue.Full:
            self.overflow_event.set()
            self.drops += 1
            LOGGER.warning("[TranscriptionQueue] Saturation -- surcharge signalee")
            return True

    def get(self, timeout: float = 0.1) -> Optional[AudioFrame]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        self.overflow_event.clear()
        drained = 0
        while True:
            try:
                self._q.get_nowait()
                drained += 1
            except queue.Empty:
                break
        return drained

    @property
    def qsize(self) -> int:
        return self._q.qsize()


# ---------------------------------------------------------------------------
# Moteur principal
# ---------------------------------------------------------------------------


class AudioCaptureEngine:
    """Proprietaire unique du microphone. Distribue des trames 16 kHz via queues.

    Un seul ``sd.RawInputStream`` est ouvert pour toute la session Jarvis.
    Un thread arriere-plan lit en continu, traite (canal stable, resample,
    accumulation), et distribue vers les queues selon le mode courant.
    """

    # Calibration canal
    _CALIBRATION_FRAMES = 20
    # Hysterese : N trames consecutives a ratio x superieur pour changer
    _HYSTERESIS_FRAMES = 10
    _HYSTERESIS_RATIO  = 3.0

    def __init__(self, device_index: Optional[int] = None) -> None:
        self.device_index    = device_index
        self.native_rate     = TARGET_SAMPLE_RATE
        self.native_channels = 1
        self._resample_ratio = 1.0

        # Flux PortAudio (unique)
        self._stream: Optional[Any] = None
        self._stream_lock = threading.RLock()
        self._running = False

        # Resampler persistant (samplerate.Resampler ou None -> fallback np.interp)
        self._resampler: Optional[Any] = None

        # Selection du canal stable
        self._calibrated        = False
        self._calibrated_channel = 0
        self._cal_energy_sums: Optional[np.ndarray] = None
        self._cal_frame_count   = 0
        self._hysteresis_counter = 0

        # VAD
        self.vad = AdaptiveVAD()

        # Periode de garde anti-echo
        self._garde_jusqu_a = 0.0

        # Queues par consommateur
        self._q_wake          = _DropOldestQueue(maxsize=4)
        self._q_transcription = _TranscriptionQueue(maxsize=16)
        self._q_stop          = _DropOldestQueue(maxsize=4)

        # Mode courant
        self._mode      = CaptureMode.NORMAL
        self._mode_lock = threading.Lock()

        # Numero de sequence monotone
        self._seq = 0

        # Buffer d'accumulation pour trames de taille exacte
        self._accumulation_buffer = np.array([], dtype=np.int16)

        # Thread de capture
        self._capture_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Initialisation materielle
    # ------------------------------------------------------------------

    def _detect_native_params(self) -> None:
        if sd is None:
            return
        try:
            dev = sd.query_devices(device=self.device_index, kind="input")
            self.native_rate     = int(dev.get("default_samplerate", 44100.0))
            self.native_channels = max(1, int(dev.get("max_input_channels", 1)))
            LOGGER.info(
                "[AudioCaptureEngine] %s (%dch @ %dHz)",
                dev.get("name", "?"), self.native_channels, self.native_rate,
            )
        except Exception as exc:
            LOGGER.warning("[AudioCaptureEngine] query_devices: %s -- fallback 1ch@16kHz", exc)
            self.native_rate     = TARGET_SAMPLE_RATE
            self.native_channels = 1

    def _init_resampler(self) -> None:
        self._resample_ratio = TARGET_SAMPLE_RATE / self.native_rate
        if self.native_rate == TARGET_SAMPLE_RATE:
            self._resampler = None
            return
        if _HAS_SAMPLERATE:
            self._resampler = _samplerate_lib.Resampler("sinc_best", channels=1)
            LOGGER.info(
                "[AudioCaptureEngine] samplerate.Resampler (ratio %.5f = %d/%d)",
                self._resample_ratio, TARGET_SAMPLE_RATE, self.native_rate,
            )
        else:
            LOGGER.warning(
                "[AudioCaptureEngine] samplerate absent -- fallback np.interp "
                "(artefacts inter-bloc possibles)"
            )

    # ------------------------------------------------------------------
    # Traitement du signal
    # ------------------------------------------------------------------

    def _resample(self, mono: np.ndarray) -> np.ndarray:
        """Reechantillonne vers 16 kHz avec etat persistant si disponible."""
        if self.native_rate == TARGET_SAMPLE_RATE:
            return mono.astype(np.int16)
        if self._resampler is not None:
            mono_f = mono.astype(np.float32) / 32768.0
            out_f  = self._resampler.process(mono_f, ratio=self._resample_ratio)
            return np.clip(out_f * 32768.0, -32768, 32767).astype(np.int16)
        # Fallback lineaire (sans etat entre blocs)
        n_out = int(len(mono) * self._resample_ratio)
        if n_out == 0:
            return np.array([], dtype=np.int16)
        xs = np.linspace(0, len(mono) - 1, len(mono))
        xd = np.linspace(0, len(mono) - 1, n_out)
        return np.interp(xd, xs, mono).astype(np.int16)

    def _select_channel(self, multichannel: np.ndarray) -> np.ndarray:
        """Retourne le canal mono stable via calibration + hysterese."""
        if self.native_channels <= 1 or multichannel.ndim == 1:
            return multichannel.ravel()

        ch_energy = np.max(np.abs(multichannel), axis=0).astype(np.float64)
        best_ch   = int(np.argmax(ch_energy))

        if not self._calibrated:
            if self._cal_energy_sums is None:
                self._cal_energy_sums = np.zeros(self.native_channels, dtype=np.float64)
            self._cal_energy_sums += ch_energy
            self._cal_frame_count  += 1
            if self._cal_frame_count >= self._CALIBRATION_FRAMES:
                self._calibrated_channel = int(np.argmax(self._cal_energy_sums))
                self._calibrated = True
                LOGGER.info("[AudioCaptureEngine] Canal calibre: %d", self._calibrated_channel)
        else:
            if best_ch != self._calibrated_channel:
                cur_e  = ch_energy[self._calibrated_channel]
                best_e = ch_energy[best_ch]
                if best_e > self._HYSTERESIS_RATIO * max(cur_e, 1.0):
                    self._hysteresis_counter += 1
                    if self._hysteresis_counter >= self._HYSTERESIS_FRAMES:
                        LOGGER.info(
                            "[AudioCaptureEngine] Canal: %d -> %d",
                            self._calibrated_channel, best_ch,
                        )
                        self._calibrated_channel = best_ch
                        self._hysteresis_counter = 0
                else:
                    self._hysteresis_counter = 0
            else:
                self._hysteresis_counter = 0

        ch = self._calibrated_channel if self._calibrated else 0
        return multichannel[:, ch]

    # ------------------------------------------------------------------
    # Distribution
    # ------------------------------------------------------------------

    def _distribute_frame(self, frame: AudioFrame) -> None:
        """Route la trame selon le mode courant et la periode de garde."""
        if self.est_en_periode_garde():
            return  # Neutralise tout pendant la garde anti-echo
        with self._mode_lock:
            mode = self._mode
        if mode == CaptureMode.SPEAKING:
            self._q_stop.put(frame)
        elif mode == CaptureMode.NORMAL:
            # Les deux consommateurs recoivent la meme trame (meme seq)
            self._q_wake.put(frame)
            self._q_transcription.put(frame)
        # CaptureMode.PAUSED : rien

    def _accumulate_and_emit(self, new_samples: np.ndarray) -> None:
        """Accumule et emet des trames de FRAME_SIZE exactement."""
        self._accumulation_buffer = np.concatenate(
            [self._accumulation_buffer, new_samples]
        )
        while len(self._accumulation_buffer) >= FRAME_SIZE:
            frame_samples             = self._accumulation_buffer[:FRAME_SIZE].copy()
            self._accumulation_buffer = self._accumulation_buffer[FRAME_SIZE:]
            is_speech = self.vad.process(frame_samples)
            frame = AudioFrame(
                seq=self._seq,
                timestamp=time.monotonic(),
                samples=frame_samples,
                is_speech=is_speech,
            )
            self._seq += 1
            self._distribute_frame(frame)

    # ------------------------------------------------------------------
    # Thread de capture
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Lit en continu depuis PortAudio, traite et distribue les trames."""
        native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))
        LOGGER.info("[AudioCaptureEngine] Thread capture demarre (bloc: %d samples)", native_block)
        while self._running:
            try:
                data, overflowed = self._stream.read(native_block)
                if overflowed:
                    LOGGER.debug("[AudioCaptureEngine] PortAudio overflow")
            except Exception as exc:
                LOGGER.debug("[AudioCaptureEngine] Erreur lecture: %s", exc)
                time.sleep(0.01)
                continue

            raw     = bytes(data)
            samples = np.frombuffer(raw, dtype=np.int16)
            if self.native_channels > 1:
                try:
                    samples = samples.reshape(-1, self.native_channels)
                    mono    = self._select_channel(samples)
                except Exception as exc:
                    LOGGER.debug("[AudioCaptureEngine] Reshape: %s", exc)
                    mono = samples.ravel()
            else:
                mono = samples

            resampled = self._resample(mono)
            self._accumulate_and_emit(resampled)

        LOGGER.info("[AudioCaptureEngine] Thread capture termine")

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def ouvrir(self) -> bool:
        """Ouvre le flux PortAudio unique et demarre le thread de capture."""
        with self._stream_lock:
            if self._running and self._stream is not None:
                return True
            if sd is None:
                LOGGER.warning("[AudioCaptureEngine] sounddevice absent")
                return False
            self._detect_native_params()
            self._init_resampler()
            native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))
            try:
                self._stream = sd.RawInputStream(
                    device=self.device_index,
                    samplerate=self.native_rate,
                    blocksize=native_block,
                    dtype="int16",
                    channels=self.native_channels,
                )
                self._stream.start()
                self._running = True
                self._capture_thread = threading.Thread(
                    target=self._capture_loop,
                    name="jarvis-audio-capture",
                    daemon=True,
                )
                self._capture_thread.start()
                LOGGER.info("[AudioCaptureEngine] Flux natif demarre")
                return True
            except Exception as exc:
                LOGGER.exception("[AudioCaptureEngine] Echec ouverture: %s", exc)
                self._stream  = None
                self._running = False
                return False

    def fermer(self) -> None:
        """Arrete le thread de capture et ferme proprement le flux PortAudio."""
        with self._stream_lock:
            self._running = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._accumulation_buffer = np.array([], dtype=np.int16)
            self._q_wake.drain()
            self._q_transcription.drain()
            self._q_stop.drain()
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        LOGGER.info("[AudioCaptureEngine] Ferme")

    def set_mode(self, mode: CaptureMode) -> None:
        """Change le mode de distribution (thread-safe)."""
        with self._mode_lock:
            prev       = self._mode
            self._mode = mode
        if prev != mode:
            LOGGER.info("[AudioCaptureEngine] Mode: %s -> %s", prev.value, mode.value)

    def drainer_et_ignorer_garde(self, duree_ms: int = 450) -> None:
        """Anti-echo post-TTS : active la periode de garde et vide toutes les queues.

        La garde commence immediatement : le thread de capture continue a lire
        PortAudio (vidant le buffer materiel) mais ne remet rien dans les queues.
        """
        self._garde_jusqu_a = time.monotonic() + duree_ms / 1000.0
        w = self._q_wake.drain()
        t = self._q_transcription.drain()
        s = self._q_stop.drain()
        self._accumulation_buffer = np.array([], dtype=np.int16)
        LOGGER.debug(
            "[AudioCaptureEngine] Garde %dms wake:%d transcription:%d stop:%d",
            duree_ms, w, t, s,
        )

    def est_en_periode_garde(self) -> bool:
        return time.monotonic() < self._garde_jusqu_a

    def lire_depuis_queue(
        self, nom: str, timeout: float = 0.1
    ) -> Optional[AudioFrame]:
        """Lecture bloquante depuis une queue nommee (wake | transcription | stop)."""
        if nom == "wake":
            return self._q_wake.get(timeout=timeout)
        if nom == "transcription":
            return self._q_transcription.get(timeout=timeout)
        if nom == "stop":
            return self._q_stop.get(timeout=timeout)
        raise ValueError(f"Queue inconnue: {nom!r}")

    def lire_trame_16k(
        self, taille: int = FRAME_SIZE
    ) -> tuple[bytes, np.ndarray, bool]:
        """Retrocompatibilite : lit une trame depuis la queue wake."""
        frame = self._q_wake.get(timeout=0.5)
        if frame is None:
            silent = np.zeros(taille, dtype=np.int16)
            return bytes(silent), silent, False
        return bytes(frame.samples), frame.samples, frame.is_speech

    def subscribe(self, nom: str = "wake") -> Any:
        """Abonnement direct à la queue sous-jacente."""
        if nom == "wake":
            return self._q_wake._q
        if nom == "transcription":
            return self._q_transcription._q
        if nom == "stop":
            return self._q_stop._q
        return self._q_wake._q

    def unsubscribe(self, *args: Any, **kwargs: Any) -> None:
        """Désabonnement (sans effet avec les queues statiques)."""
        pass

    def read(self, size: int = FRAME_SIZE) -> tuple[bytes, bool]:
        """Interface compatible stream pour transcrire_flux."""
        frame = self._q_transcription.get(timeout=0.2)
        if frame is None:
            return bytes(np.zeros(size, dtype=np.int16)), False
        return bytes(frame.samples), False


# ---------------------------------------------------------------------------
# Singleton thread-safe
# ---------------------------------------------------------------------------

_CAPTURE_ENGINE: Optional[AudioCaptureEngine] = None
_CAPTURE_LOCK = threading.Lock()


def get_audio_capture_engine(
    device_index: Optional[int] = None,
) -> AudioCaptureEngine:
    """Retourne le singleton du moteur de capture audio (thread-safe).

    Si ``device_index`` differe du peripherique actuel, l'ancien moteur
    est ferme proprement avant creation d'un nouveau.
    """
    global _CAPTURE_ENGINE
    with _CAPTURE_LOCK:
        if _CAPTURE_ENGINE is None:
            _CAPTURE_ENGINE = AudioCaptureEngine(device_index=device_index)
        elif (
            device_index is not None
            and _CAPTURE_ENGINE.device_index != device_index
        ):
            _CAPTURE_ENGINE.fermer()
            _CAPTURE_ENGINE = AudioCaptureEngine(device_index=device_index)
        return _CAPTURE_ENGINE
