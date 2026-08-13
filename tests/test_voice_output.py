import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from capabilities.voice_output import parler_a_voix_haute
from core.voice_state import VoiceState, _set_voice_state, get_voice_state


class FakeEngine:
    def __init__(self):
        self.spoken = []
        self.waited = False

    def say(self, text):
        self.spoken.append(text)

    def runAndWait(self):
        self.waited = True


class VoiceOutputTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)

    def test_reads_text_and_returns_to_idle(self):
        engine = FakeEngine()
        _set_voice_state(VoiceState.THINKING)
        with patch.dict(sys.modules, {"pyttsx3": SimpleNamespace(init=lambda: engine)}):
            parler_a_voix_haute("Bonjour")

        self.assertEqual(["Bonjour"], engine.spoken)
        self.assertTrue(engine.waited)
        self.assertEqual(VoiceState.IDLE, get_voice_state())

    def test_tts_failure_is_contained_and_returns_to_idle(self):
        _set_voice_state(VoiceState.THINKING)
        with patch.dict(sys.modules, {"pyttsx3": SimpleNamespace(init=lambda: (_ for _ in ()).throw(RuntimeError("audio")))}):
            parler_a_voix_haute("Bonjour")

        self.assertEqual(VoiceState.IDLE, get_voice_state())

    def test_refuses_to_speak_when_not_thinking(self):
        with patch.dict(sys.modules, {"pyttsx3": SimpleNamespace(init=lambda: self.fail("TTS ne doit pas démarrer"))}):
            parler_a_voix_haute("Bonjour")

        self.assertEqual(VoiceState.IDLE, get_voice_state())
