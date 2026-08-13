import unittest
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
