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
import os
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
    from scipy.signal import resample_poly as _scipy_resample_poly
    from math import gcd as _math_gcd
    _HAS_SCIPY = True
except ImportError:
    _scipy_resample_poly = None  # type: ignore[assignment]
    _math_gcd = None  # type: ignore[assignment]
    _HAS_SCIPY = False

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000
FRAME_SIZE = 1_280  # 80 ms @ 16 kHz (openWakeWord + Vosk)
# Alias de retrocompatibilite
DEFAULT_FRAME_LENGTH = FRAME_SIZE


def _get_default_input_device_index() -> Optional[int]:
    """Lit le périphérique d'entrée par défaut exposé par le backend hôte."""
    if sd is None:
        return None
    try:
        default_device = sd.default.device
        try:
            # sounddevice expose un _InputOutputPair indexable, qui n'est pas
            # nécessairement une tuple/list native.
            index = default_device[0]
        except (TypeError, IndexError, KeyError):
            index = default_device
        if index is None or int(index) < 0:
            return None
        return int(index)
    except Exception:
        return None


def _publish_audio_input_status(available: bool, reason: Optional[str] = None) -> None:
    """Publie au HUD le périphérique hôte actuellement utilisé ou attendu."""
    device_name = None
    if available and sd is not None:
        try:
            index = _get_default_input_device_index()
            if index is not None:
                device_name = sd.query_devices(device=index, kind="input").get("name")
        except Exception:
            pass
    try:
        from jarvis.voice_state import _set_voice_audio_input
        _set_voice_audio_input({"available": available, "device": device_name, "reason": reason})
    except Exception:
        LOGGER.debug("État microphone HUD indisponible", exc_info=True)


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
    
    Améliorations pour la robustesse au bruit :
    - Hystérésis (nécessite N trames consécutives pour transition)
    - Moyenne glissante de l'énergie pour lisser les pics
    - Adaptation plus lente du plancher de bruit
    - Détection de saturation audio (clipping)
    - Filtre spectral simple pour distinguer parole vs bruit continu
    """

    def __init__(
        self,
        alpha: float = 0.02,  # Plus lent pour éviter de monter le seuil trop vite
        min_ratio: float = 2.5,  # Ratio plus conservateur
        min_threshold: int = 150,
        hysteresis_frames: int = 3,  # Nombre de trames consécutives requises
    ) -> None:
        self.noise_floor = 50.0
        self.alpha = alpha
        self.min_ratio = min_ratio
        self.min_threshold = min_threshold
        self.is_speech_active = False
        
        # Hystérésis pour éviter les fluctuations
        self.hysteresis_frames = hysteresis_frames
        self.consecutive_speech = 0
        self.consecutive_silence = 0
        
        # Moyenne glissante de l'énergie (fenêtre de 5 trames)
        self.energy_window = []
        self.energy_window_size = 5
        
        # Détection de saturation (clipping)
        self.saturation_threshold = 30000  # Près de max int16 (32767)
        self.saturation_count = 0
        self.saturation_window = []
        self.saturation_window_size = 10
        
        # Filtre spectral simple (ratio zero-crossing)
        self.zcr_window = []
        self.zcr_window_size = 5

    def process(self, samples: np.ndarray) -> bool:
        if samples.size == 0:
            return False
        
        # Calcul de l'énergie avec lissage
        # Convert before abs: np.abs(int16(-32768)) overflows and stays negative.
        magnitudes = np.abs(samples.astype(np.float32, copy=False))
        energy = float(np.max(magnitudes))
        self.energy_window.append(energy)
        if len(self.energy_window) > self.energy_window_size:
            self.energy_window.pop(0)
        smoothed_energy = sum(self.energy_window) / len(self.energy_window)
        
        # Détection de saturation (clipping) - ignore les trames saturées
        saturated = np.any(magnitudes > self.saturation_threshold)
        self.saturation_window.append(saturated)
        if len(self.saturation_window) > self.saturation_window_size:
            self.saturation_window.pop(0)
        saturation_ratio = sum(self.saturation_window) / len(self.saturation_window)
        
        # Si saturation excessive, ignorer cette trame pour le VAD
        if saturation_ratio > 0.5:
            return self.is_speech_active  # Maintenir l'état actuel
        
        # Calcul du zero-crossing rate (ZCR) pour distinguer parole vs bruit continu
        # La parole a un ZCR plus variable que la musique ou le bruit blanc
        zero_crossings = np.sum(np.diff(np.sign(samples)) != 0)
        zcr = zero_crossings / len(samples)
        self.zcr_window.append(zcr)
        if len(self.zcr_window) > self.zcr_window_size:
            self.zcr_window.pop(0)
        avg_zcr = sum(self.zcr_window) / len(self.zcr_window)
        
        # Ajustement dynamique du seuil basé sur le ZCR
        # Un ZCR très bas ou très constant indique du bruit continu (musique, ventilateur)
        zcr_factor = 1.0
        if len(self.zcr_window) >= 3:
            zcr_std = np.std(self.zcr_window)
            # Si le ZCR est très stable (faible écart-type), c'est probablement du bruit continu
            if zcr_std < 0.02:
                zcr_factor = 1.5  # Augmenter le seuil pour les bruits continus
        
        threshold = max(self.noise_floor * self.min_ratio * zcr_factor, float(self.min_threshold))
        raw_speech = smoothed_energy > threshold
        
        # Hystérésis : nécessite plusieurs trames consécutives
        if raw_speech:
            self.consecutive_speech += 1
            self.consecutive_silence = 0
        else:
            self.consecutive_silence += 1
            self.consecutive_speech = 0
        
        # Transition parole -> silence
        if self.is_speech_active and self.consecutive_silence >= self.hysteresis_frames:
            self.is_speech_active = False
        # Transition silence -> parole
        elif not self.is_speech_active and self.consecutive_speech >= self.hysteresis_frames:
            self.is_speech_active = True
        
        # Mise a jour du plancher UNIQUEMENT en periode calme reconnue (hystérésis appliquée)
        if not self.is_speech_active and self.consecutive_silence >= self.hysteresis_frames * 2:
            self.noise_floor = (
                (1.0 - self.alpha) * self.noise_floor + self.alpha * smoothed_energy
            )
        
        return self.is_speech_active

    def calibrate_noise_floor(self, energies: list[float] | np.ndarray) -> tuple[float, float]:
        """Auto-calibration du bruit ambiant par mesure de la médiane sur ~1 seconde.

        Calcule la médiane du bruit de fond (robuste aux transitoires et bruits brefs).
        Fixe des seuils fiables qui évitent que le VAD ne sature ou ne reste bloqué en parole.
        Renvoie (noise_floor, seuil_effectif).
        """
        if len(energies) == 0:
            return self.noise_floor, float(self.min_threshold)

        arr = np.array(energies, dtype=np.float32)
        med = float(np.median(arr))

        if med <= 0.0:
            self.noise_floor = 50.0
            self.min_threshold = 150
        else:
            self.noise_floor = max(30.0, med)
            # Seuil minimal calé au-dessus de la médiane pour éviter toute saturation permanente
            self.min_threshold = max(150, int(med * 2.0))

        self.is_speech_active = False
        self.consecutive_speech = 0
        self.consecutive_silence = 0
        self.energy_window.clear()
        self.saturation_count = 0
        self.saturation_window.clear()
        self.zcr_window.clear()
        effective_threshold = max(self.noise_floor * self.min_ratio, float(self.min_threshold))
        LOGGER.info(
            "[AdaptiveVAD] Auto-calibré: médiane bruit=%.1f, min_seuil=%d, seuil_effectif=%.1f",
            self.noise_floor, self.min_threshold, effective_threshold,
        )
        return self.noise_floor, effective_threshold

    def reset_floor(self, default_val: float = 50.0) -> None:
        self.noise_floor = default_val
        self.min_threshold = max(150, int(default_val * 2.0)) if default_val > 50.0 else 150
        self.is_speech_active = False
        self.consecutive_speech = 0
        self.consecutive_silence = 0
        self.energy_window.clear()
        self.saturation_count = 0
        self.saturation_window.clear()
        self.zcr_window.clear()


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
    """Tampon glissant de transcription privilégiant la continuité vocale.

    En saturation, la trame la plus ancienne est évincée. Aucun événement
    d'abandon n'est émis : le recognizer poursuit l'énoncé avec les données les
    plus récentes, ce qui est préférable à une annulation complète.
    """

    def __init__(self, maxsize: int = 64, active_consumer: bool = True) -> None:
        self._q: queue.Queue[AudioFrame] = queue.Queue(maxsize=maxsize)
        self.overflow_event = threading.Event()
        self.drops = 0
        self.active_consumer = active_consumer
        self._last_warning = 0.0

    def put(self, frame: AudioFrame) -> bool:
        """Insere ; si pleine, applique un tampon glissant et limite les alertes."""
        try:
            self._q.put_nowait(frame)
            return False
        except queue.Full:
            if not self.active_consumer:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._q.put_nowait(frame)
                except queue.Full:
                    pass
                return False
            self.drops += 1
            now = time.monotonic()
            if now - self._last_warning >= 5.0:
                self._last_warning = now
                LOGGER.warning("[TranscriptionQueue] Saturation -- surcharge signalee (tampon glissant actif)")
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                pass
            return True

    def get(self, timeout: float = 0.1) -> Optional[AudioFrame]:
        self.active_consumer = True
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        self.active_consumer = False
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
        # None signifie que GreatOS suit en continu le périphérique par défaut
        # de l'hôte. Un index explicite reste réservé aux intégrations/tests.
        self._follow_system_default = device_index is None
        self.device_index    = device_index
        self.native_rate     = TARGET_SAMPLE_RATE
        self.native_channels = 1
        self._resample_ratio = 1.0

        # Flux PortAudio (unique)
        self._stream: Optional[Any] = None
        self._stream_lock = threading.RLock()
        self._running = False
        self._default_switch_pending = False

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
        self._q_clap          = _DropOldestQueue(maxsize=4)
        self._q_transcription = _TranscriptionQueue(maxsize=64, active_consumer=False)
        self._q_stop          = _DropOldestQueue(maxsize=4)

        # Mode courant
        self._mode      = CaptureMode.NORMAL
        self._mode_lock = threading.Lock()

        # Numero de sequence monotone
        self._seq = 0

        # Buffer d'accumulation pour trames de taille exacte
        self._accumulation_buffer = np.array([], dtype=np.int16)

        # Auto-calibration du bruit ambiant au lancement
        self._noise_calibrated = False
        self._noise_cal_energies: list[float] = []
        self._noise_cal_target_frames = 12  # ~1.0 seconde (12 * 80ms = 960ms)

        # Thread de capture
        self._capture_thread: Optional[threading.Thread] = None
        self._next_default_check = 0.0

    # ------------------------------------------------------------------
    # Initialisation materielle
    # ------------------------------------------------------------------

    def _detect_native_params(self) -> None:
        if sd is None:
            return
        try:
            if self._follow_system_default:
                self.device_index = _get_default_input_device_index()
                if self.device_index is None:
                    raise RuntimeError("Windows ne signale aucun micro par défaut")
            dev = sd.query_devices(device=self.device_index, kind="input")
            sr = int(dev.get("default_samplerate", 44100.0))
            channels = max(1, int(dev.get("max_input_channels", 1)))

            # Capture au taux natif matériel de la carte son (généralement 48 000 Hz sur PC portable Windows avec Synaptics).
            # Vérifier si 48000 Hz est supporté pour éviter le mixage dégradant de l'hôte.
            env_sr = os.environ.get("JARVIS_AUDIO_SAMPLE_RATE")
            candidates = [int(env_sr)] if env_sr else [48000, sr, 44100, TARGET_SAMPLE_RATE]
            for candidate in candidates:
                try:
                    sd.check_input_settings(
                        device=self.device_index,
                        samplerate=candidate,
                        channels=channels,
                        dtype="int16",
                    )
                    sr = candidate
                    break
                except Exception:
                    continue

            self.native_rate     = sr
            self.native_channels = channels
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
            # sinc_fastest offre un filtrage sinc temps réel sans latence avec état persistant
            self._resampler = _samplerate_lib.Resampler("sinc_fastest", channels=1)
            LOGGER.info(
                "[AudioCaptureEngine] samplerate.Resampler sinc_fastest (ratio %.5f = %d/%d)",
                self._resample_ratio, TARGET_SAMPLE_RATE, self.native_rate,
            )
        elif _HAS_SCIPY:
            self._resampler = None
            LOGGER.info(
                "[AudioCaptureEngine] scipy.signal.resample_poly actif (ratio %.5f = %d/%d)",
                self._resample_ratio, TARGET_SAMPLE_RATE, self.native_rate,
            )
        else:
            self._resampler = None
            LOGGER.warning(
                "[AudioCaptureEngine] samplerate et scipy absents -- fallback np.interp "
                "(artefacts inter-bloc possibles)"
            )

    # ------------------------------------------------------------------
    # Traitement du signal
    # ------------------------------------------------------------------

    def _resample(self, mono: np.ndarray) -> np.ndarray:
        """Reechantillonne vers 16 kHz avec etat persistant (samplerate) ou polyphase (scipy)."""
        if self.native_rate == TARGET_SAMPLE_RATE:
            return mono.astype(np.int16)
        if self._resampler is not None:
            mono_f = mono.astype(np.float32) / 32768.0
            out_f  = self._resampler.process(mono_f, ratio=self._resample_ratio)
            return np.clip(out_f * 32768.0, -32768, 32767).astype(np.int16)
        if _HAS_SCIPY and _scipy_resample_poly is not None and _math_gcd is not None:
            g = _math_gcd(TARGET_SAMPLE_RATE, self.native_rate)
            up = TARGET_SAMPLE_RATE // g
            down = self.native_rate // g
            mono_f = mono.astype(np.float32)
            out_f = _scipy_resample_poly(mono_f, up, down)
            return np.clip(out_f, -32768, 32767).astype(np.int16)
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
            self._q_wake.put(frame)
            self._q_clap.put(frame)
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
        """Lit en continu depuis PortAudio, traite et distribue les trames.
        
        Inclut une logique de reconnexion automatique en cas de déconnexion du micro.
        """
        native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))
        LOGGER.info("[AudioCaptureEngine] Thread capture demarre (bloc: %d samples)", native_block)
        
        consecutive_errors = 0
        max_consecutive_errors = 10
        reconnect_delay = 1.0
        
        while self._running:
            # PortAudio ouvre un flux sur un périphérique concret. Si Windows
            # change son micro par défaut (ex. casque Bluetooth), fermer ce flux
            # puis en ouvrir un seul sur le nouveau défaut.
            now = time.monotonic()
            if self._follow_system_default and now >= self._next_default_check:
                self._next_default_check = now + 1.0
                default_index = _get_default_input_device_index()
                if default_index != self.device_index or (self._stream is None and default_index is not None):
                    LOGGER.info(
                        "[AudioCaptureEngine] Défaut micro hôte : %s -> %s",
                        self.device_index, default_index,
                    )
                    self._default_switch_pending = True
                    self.device_index = default_index
                    if default_index is None:
                        self._attempt_reconnect()
                        _publish_audio_input_status(False, "no_host_default_input")
                        LOGGER.warning("[AudioCaptureEngine] Aucun micro par défaut Windows disponible")
                    else:
                        _publish_audio_input_status(True, "switching_to_default_input")
                        self._attempt_reconnect()
                        native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))

            if self._stream is None:
                time.sleep(0.1)
                continue

            try:
                data, overflowed = self._stream.read(native_block)
                if overflowed:
                    LOGGER.debug("[AudioCaptureEngine] PortAudio overflow")
                consecutive_errors = 0  # Reset compteur d'erreurs
            except Exception as exc:
                consecutive_errors += 1
                LOGGER.warning(
                    "[AudioCaptureEngine] Erreur lecture (%d/%d): %s",
                    consecutive_errors, max_consecutive_errors, exc
                )
                
                # Si trop d'erreurs consécutives : tentative de reconnexion
                if consecutive_errors >= max_consecutive_errors:
                    LOGGER.error("[AudioCaptureEngine] Trop d'erreurs - tentative de reconnexion")
                    self._attempt_reconnect()
                    native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))
                    consecutive_errors = 0
                    time.sleep(reconnect_delay)
                    continue
                
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

    def _close_stream(self) -> None:
        """Ferme le flux courant sans arrêter le thread propriétaire."""
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def _attempt_reconnect(self) -> bool:
        """Reconnecte le flux depuis le thread de capture courant.

        Ne pas appeler ``ouvrir()`` ici : cette méthode démarre un nouveau
        thread de capture. Le thread courant est déjà le propriétaire du
        microphone et doit reprendre la lecture après la reconnexion.
        """
        LOGGER.info("[AudioCaptureEngine] Tentative de reconnexion du micro...")

        self._close_stream()
        with self._stream_lock:
            self._accumulation_buffer = np.array([], dtype=np.int16)
            self._q_wake.drain()
            self._q_clap.drain()
            self._q_transcription.drain()
            self._q_stop.drain()
        
        # Réinitialiser le VAD pour éviter un plancher de bruit erroné
        self.vad.reset_floor()
        
        # Attendre un peu avant reconnexion
        time.sleep(0.5)
        
        # Réouvrir seulement le flux matériel. Le thread courant reprend
        # naturellement sa boucle; en démarrer un second ferait lire le même
        # flux par deux consommateurs concurrents.
        with self._stream_lock:
            if not self._running or sd is None:
                return False
            try:
                if self._follow_system_default:
                    self.device_index = _get_default_input_device_index()
                    if self.device_index is None:
                        LOGGER.warning("[AudioCaptureEngine] Reconnexion en attente du micro par défaut Windows")
                        _publish_audio_input_status(False, "no_host_default_input")
                        return False
                self._detect_native_params()
                self._init_resampler()
                native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))
                stream = sd.RawInputStream(
                    device=self.device_index,
                    samplerate=self.native_rate,
                    blocksize=native_block,
                    dtype="int16",
                    channels=self.native_channels,
                )
                stream.start()
                self._stream = stream
                self._default_switch_pending = False
                _publish_audio_input_status(True)
                LOGGER.info("[AudioCaptureEngine] Micro reconnecté")
                return True
            except Exception as exc:
                self._stream = None
                LOGGER.warning("[AudioCaptureEngine] Reconnexion échouée: %s", exc)
                _publish_audio_input_status(
                    _get_default_input_device_index() is not None,
                    "input_stream_open_failed",
                )
                return False

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def ouvrir(self) -> bool:
        """Ouvre le flux PortAudio unique et demarre le thread de capture."""
        with self._stream_lock:
            if self._running:
                # Le thread de capture reste propriétaire pendant une
                # reconnexion; ne jamais en lancer un second.
                return self._stream is not None
            if sd is None:
                LOGGER.warning("[AudioCaptureEngine] sounddevice absent")
                return False
            try:
                if self._follow_system_default and _get_default_input_device_index() is None:
                    LOGGER.warning("[AudioCaptureEngine] Aucun micro par défaut Windows disponible")
                    _publish_audio_input_status(False, "no_host_default_input")
                    return False
                self._detect_native_params()
                self._init_resampler()
                native_block = int(FRAME_SIZE * (self.native_rate / TARGET_SAMPLE_RATE))
                self._stream = sd.RawInputStream(
                    device=self.device_index,
                    samplerate=self.native_rate,
                    blocksize=native_block,
                    dtype="int16",
                    channels=self.native_channels,
                )
                self._stream.start()
                self._running = True
                _publish_audio_input_status(True)
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
                _publish_audio_input_status(
                    _get_default_input_device_index() is not None,
                    "input_stream_open_failed",
                )
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
            self._q_clap.drain()
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
        c = self._q_clap.drain()
        t = self._q_transcription.drain()
        s = self._q_stop.drain()
        self._accumulation_buffer = np.array([], dtype=np.int16)
        LOGGER.debug(
            "[AudioCaptureEngine] Garde %dms wake:%d clap:%d transcription:%d stop:%d",
            duree_ms, w, c, t, s,
        )

    def est_en_periode_garde(self) -> bool:
        return time.monotonic() < self._garde_jusqu_a

    def lire_depuis_queue(
        self, nom: str, timeout: float = 0.1
    ) -> Optional[AudioFrame]:
        """Lecture bloquante depuis une queue nommee (wake | clap | transcription | stop)."""
        if nom == "wake":
            return self._q_wake.get(timeout=timeout)
        if nom == "clap":
            return self._q_clap.get(timeout=timeout)
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
        if nom == "clap":
            return self._q_clap._q
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


def get_audio_capture_status() -> dict[str, Any]:
    """Expose le défaut de l'hôte et le flux GreatOS, sans ouvrir de micro."""
    default_index = _get_default_input_device_index()
    default_info: dict[str, Any] = {"available": False, "index": default_index, "name": None}
    if default_index is not None and sd is not None:
        try:
            device = sd.query_devices(device=default_index, kind="input")
            host_api = device.get("hostapi")
            try:
                host_api_name = sd.query_hostapis(host_api).get("name") if host_api is not None else None
            except Exception:
                host_api_name = None
            default_info.update({
                "available": int(device.get("max_input_channels", 0)) > 0,
                "name": device.get("name"),
                "host_api": host_api_name,
            })
        except Exception as exc:
            default_info["error"] = str(exc)

    with _CAPTURE_LOCK:
        engine = _CAPTURE_ENGINE
    active_index = engine.device_index if engine is not None else None
    active_name = None
    if active_index is not None and sd is not None:
        try:
            active_name = sd.query_devices(device=active_index, kind="input").get("name")
        except Exception:
            pass
    stream_open = bool(engine and engine._stream is not None)
    try:
        stream_active = bool(stream_open and getattr(engine._stream, "active", True))
    except Exception:
        stream_active = False
    follows_system_default = bool(engine and engine._follow_system_default)
    active_matches_default = (
        default_index is not None
        and active_index == default_index
        and not engine._default_switch_pending
        if follows_system_default
        else None
    )
    return {
        "default_input": default_info,
        "active_input": {"index": active_index, "name": active_name},
        "stream_open": stream_open,
        "stream_active": stream_active,
        "follows_system_default": follows_system_default,
        "default_switch_pending": bool(engine and engine._default_switch_pending),
        "active_matches_default": active_matches_default,
    }


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
