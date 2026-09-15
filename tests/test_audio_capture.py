import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from jarvis.audio_capture import (
    AudioCaptureEngine,
    AudioFrame,
    CaptureMode,
    AdaptiveVAD,
    _DropOldestQueue,
    _TranscriptionQueue,
    FRAME_SIZE,
    get_audio_capture_engine,
)


class FakePortAudioStream:
    def __init__(self, channels=1, samplerate=16000):
        self.channels = channels
        self.samplerate = samplerate
        self.active = True
        self.read_calls = 0

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.active = False

    def read(self, frames):
        self.read_calls += 1
        data = np.zeros(frames * self.channels, dtype=np.int16)
        return data.tobytes(), False


class AudioCaptureTests(unittest.TestCase):
    def tearDown(self):
        engine = get_audio_capture_engine()
        engine.fermer()

    def test_single_stream_non_concurrency(self):
        """Vérifie qu'un seul sd.RawInputStream est ouvert pour toute la session."""
        stream_instances = []

        def mock_raw_input_stream(**kwargs):
            inst = FakePortAudioStream(channels=kwargs.get('channels', 1), samplerate=kwargs.get('samplerate', 16000))
            stream_instances.append(inst)
            return inst

        fake_sd = SimpleNamespace(
            RawInputStream=mock_raw_input_stream,
            query_devices=lambda **kw: {'name': 'Mock Mic', 'default_samplerate': 16000.0, 'max_input_channels': 1}
        )

        with patch('jarvis.audio_capture.sd', fake_sd):
            engine = AudioCaptureEngine(device_index=1)
            self.assertTrue(engine.ouvrir())
            # Deuxième appel à ouvrir() ne doit pas réouvrir de stream
            self.assertTrue(engine.ouvrir())

            # Vérifier qu'un seul RawInputStream a été instancié
            self.assertEqual(1, len(stream_instances))

            engine.fermer()
            self.assertFalse(stream_instances[0].active)

    def test_vad_noise_floor_only_updates_during_silence(self):
        """La VAD ne doit mettre à jour le plancher de bruit que pendant le silence."""
        vad = AdaptiveVAD(alpha=0.1, min_ratio=2.0, min_threshold=100)
        vad.reset_floor(50.0)

        # 1. Trame silencieuse (énergie 40 < seuil 100) -> plancher s'adapte
        silence = np.full(FRAME_SIZE, 40, dtype=np.int16)
        is_speech = vad.process(silence)
        self.assertFalse(is_speech)
        expected_floor = (1.0 - 0.1) * 50.0 + 0.1 * 40.0
        self.assertAlmostEqual(expected_floor, vad.noise_floor)

        # 2. Trame de parole intense (énergie 2000 > seuil 100) -> plancher NE CHANGE PAS
        current_floor = vad.noise_floor
        speech = np.full(FRAME_SIZE, 2000, dtype=np.int16)
        is_speech = vad.process(speech)
        self.assertTrue(is_speech)
        self.assertEqual(current_floor, vad.noise_floor)

    def test_channel_calibration_and_hysteresis(self):
        """Calibration sur 20 trames, puis hystérèse marquée avant changement de canal."""
        engine = AudioCaptureEngine()
        engine.native_channels = 4
        engine.native_rate = 16000

        # Phase 1 : 20 trames où le canal 2 est le plus fort
        for _ in range(20):
            block = np.zeros((FRAME_SIZE, 4), dtype=np.int16)
            block[:, 0] = 50
            block[:, 1] = 80
            block[:, 2] = 500  # Canal 2 domine
            block[:, 3] = 30
            mono = engine._select_channel(block)

        self.assertTrue(engine._calibrated)
        self.assertEqual(2, engine._calibrated_channel)

        # Phase 2 : canal 0 devient 1.2x plus fort (ratio < 3x) -> pas de changement
        for _ in range(15):
            block = np.zeros((FRAME_SIZE, 4), dtype=np.int16)
            block[:, 0] = 600   # 1.2x canal 2
            block[:, 2] = 500
            mono = engine._select_channel(block)
        self.assertEqual(2, engine._calibrated_channel)

        # Phase 3 : canal 0 devient 5x plus fort pendant 9 trames -> pas encore basculé
        for _ in range(9):
            block = np.zeros((FRAME_SIZE, 4), dtype=np.int16)
            block[:, 0] = 2500  # > 3x canal 2
            block[:, 2] = 500
            mono = engine._select_channel(block)
        self.assertEqual(2, engine._calibrated_channel)

        # 10e trame consécutive -> bascule sur canal 0
        block = np.zeros((FRAME_SIZE, 4), dtype=np.int16)
        block[:, 0] = 2500
        block[:, 2] = 500
        mono = engine._select_channel(block)
        self.assertEqual(0, engine._calibrated_channel)

    def test_drop_oldest_queue_policy(self):
        """_DropOldestQueue remplace le plus ancien quand pleine."""
        q = _DropOldestQueue(maxsize=3)
        self.assertFalse(q.put(AudioFrame(1, np.zeros(10), False)))
        self.assertFalse(q.put(AudioFrame(2, np.zeros(10), False)))
        self.assertFalse(q.put(AudioFrame(3, np.zeros(10), False)))
        self.assertEqual(0, q.drops)

        # 4e trame : surcharge, perte signalée et trame 1 jetée
        dropped = q.put(AudioFrame(4, np.zeros(10), False))
        self.assertTrue(dropped)
        self.assertEqual(1, q.drops)
        self.assertTrue(q.drop_event.is_set())

        # Le plus ancien restant doit être 2
        f = q.get(timeout=0.01)
        self.assertIsNotNone(f)
        self.assertEqual(2, f.seq)

    def test_transcription_queue_keeps_latest_frames_without_abandoning_utterance(self):
        """La saturation conserve les trames récentes sans déclencher d'abandon."""
        q = _TranscriptionQueue(maxsize=2)
        self.assertFalse(q.put(AudioFrame(1, np.zeros(10), False)))
        self.assertFalse(q.put(AudioFrame(2, np.zeros(10), False)))
        self.assertFalse(q.overflow_event.is_set())

        # 3e trame : dépassement
        overflow = q.put(AudioFrame(3, np.zeros(10), False))
        self.assertTrue(overflow)
        self.assertFalse(q.overflow_event.is_set())
        self.assertEqual(1, q.drops)
        frame = q.get(timeout=0.01)
        self.assertIsNotNone(frame)
        self.assertEqual(2, frame.seq)

    def test_capture_modes_routing(self):
        """Vérifie le routage des trames selon CaptureMode."""
        engine = AudioCaptureEngine()
        engine.native_channels = 1
        engine.native_rate = 16000

        frame = AudioFrame(1, np.zeros(FRAME_SIZE, dtype=np.int16), False)

        # Mode NORMAL : wake, clap et transcription alimentés
        engine.set_mode(CaptureMode.NORMAL)
        engine._distribute_frame(frame)
        self.assertEqual(1, engine._q_wake.qsize)
        self.assertEqual(1, engine._q_clap.qsize)
        self.assertEqual(1, engine._q_transcription.qsize)
        self.assertEqual(0, engine._q_stop.qsize)
        engine._q_wake.drain()
        engine._q_clap.drain()
        engine._q_transcription.drain()

        # Mode SPEAKING : seul stop est alimenté
        engine.set_mode(CaptureMode.SPEAKING)
        engine._distribute_frame(frame)
        self.assertEqual(0, engine._q_wake.qsize)
        self.assertEqual(0, engine._q_clap.qsize)
        self.assertEqual(0, engine._q_transcription.qsize)
        self.assertEqual(1, engine._q_stop.qsize)
        engine._q_stop.drain()

        # Mode PAUSED : aucune queue alimentée
        engine.set_mode(CaptureMode.PAUSED)
        engine._distribute_frame(frame)
        self.assertEqual(0, engine._q_wake.qsize)
        self.assertEqual(0, engine._q_clap.qsize)
        self.assertEqual(0, engine._q_transcription.qsize)
        self.assertEqual(0, engine._q_stop.qsize)

    def test_guard_period_neutralizes_frames(self):
        """Pendant la période de garde anti-écho, les trames ne sont pas distribuées."""
        engine = AudioCaptureEngine()
        engine.drainer_et_ignorer_garde(duree_ms=200)
        self.assertTrue(engine.est_en_periode_garde())

        frame = AudioFrame(1, np.zeros(FRAME_SIZE, dtype=np.int16), False)
        engine._distribute_frame(frame)
        self.assertEqual(0, engine._q_wake.qsize)
        self.assertEqual(0, engine._q_clap.qsize)
        self.assertEqual(0, engine._q_transcription.qsize)
