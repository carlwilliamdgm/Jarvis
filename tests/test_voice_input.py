import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

import jarvis
from capabilities import voice_input
from core.voice_state import VoiceState, _set_voice_state, get_voice_state


class FakeRecognizer:
    def __init__(self):
        self.calls = 0

    def AcceptWaveform(self, _data):
        self.calls += 1
        return self.calls == 1

    def Result(self):
        return '{"text": "bonjour jarvis"}'

    def PartialResult(self):
        return '{"partial": ""}'

    def FinalResult(self):
        return '{"text": ""}'


class FakeStream:
    def read(self, _size):
        return b"audio", False


class FakeWakeWordStream:
    def __init__(self):
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        self.reads += 1
        return b"\x00\x00" * _size, False


class FakeWakeWordModel:
    def __init__(self, score, stop_event=None):
        self.score = score
        self.stop_event = stop_event

    def predict(self, _samples):
        if self.stop_event:
            self.stop_event.set()
        return {"hey_jarvis": self.score}


class VoiceInputTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)

    def test_transcription_and_pipeline_nominal(self):
        with patch.object(voice_input, "_new_recognizer", return_value=FakeRecognizer()), \
             patch.object(voice_input, "_soumettre_au_pipeline", return_value=True) as submit:
            text = voice_input.transcrire_et_soumettre(FakeStream())

        self.assertEqual("bonjour jarvis", text)
        submit.assert_called_once_with("bonjour jarvis")

    def test_transcription_failure_returns_idle(self):
        with patch.object(voice_input, "transcrire_flux", return_value=None):
            text = voice_input.transcrire_et_soumettre(FakeStream())

        self.assertIsNone(text)
        self.assertEqual(VoiceState.IDLE, get_voice_state())

    def test_busy_pipeline_is_ignored_without_waiting(self):
        self.assertTrue(jarvis.INTERACTION_LOCK.acquire(blocking=False))
        try:
            _set_voice_state(VoiceState.LISTENING)
            with patch.object(voice_input, "_creer_contexte_pipeline", return_value=([], {})):
                self.assertFalse(voice_input._soumettre_au_pipeline("bonjour"))
        finally:
            jarvis.INTERACTION_LOCK.release()

        self.assertEqual(VoiceState.IDLE, get_voice_state())

    def test_openwakeword_detection_starts_shared_transcription_path(self):
        stream = FakeWakeWordStream()
        fake_sounddevice = SimpleNamespace(RawInputStream=lambda **_kwargs: stream)
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}), \
             patch.object(voice_input, "_new_wake_word_model", return_value=FakeWakeWordModel(0.8)), \
             patch.object(voice_input, "transcrire_et_soumettre", return_value="bonjour") as transcribe:
            text = voice_input.écouter_et_transcrire()

        self.assertEqual("bonjour", text)
        transcribe.assert_called_once_with(stream)

    def test_openwakeword_below_threshold_does_not_transcribe(self):
        stream = FakeWakeWordStream()
        fake_sounddevice = SimpleNamespace(RawInputStream=lambda **_kwargs: stream)
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}), \
             patch.object(
                 voice_input,
                 "_new_wake_word_model",
                 return_value=FakeWakeWordModel(0.1, voice_input._STOP_EVENT),
             ), \
             patch.object(voice_input, "transcrire_et_soumettre") as transcribe:
            self.assertIsNone(voice_input.écouter_et_transcrire())

        voice_input._STOP_EVENT.clear()
        transcribe.assert_not_called()
