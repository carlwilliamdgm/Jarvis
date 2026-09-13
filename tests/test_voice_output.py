import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jarvis import voice_input
from jarvis.voice_output import demander_arret_tts, _is_stop_command, _lire_avec_interruption, parler_a_voix_haute
from jarvis.voice_state import VoiceState, _set_voice_state, get_voice_state


class FakeEngine:
    def __init__(self):
        self.spoken = []
        self.waited = False

    pass


class FakeStopRecognizer:
    def AcceptWaveform(self, _data):
        return True

    def Result(self):
        return '{"text": "arrête Jarvis"}'

    def PartialResult(self):
        return '{"partial": ""}'


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return b"audio", False


class FakePlayback:
    active = True


class VoiceOutputTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)

    def test_reads_text_and_returns_to_listening(self):
        voice = FakeEngine()
        _set_voice_state(VoiceState.THINKING)
        with patch("jarvis.voice_output.get_piper_voice", return_value=voice), \
             patch("jarvis.voice_output._synthesise", return_value=(object(), 22_050)) as synthesize, \
             patch("jarvis.voice_output._lire_avec_interruption") as read:
            parler_a_voix_haute("Bonjour")

        synthesize.assert_called_once_with(voice, "Bonjour")
        read.assert_called_once()
        self.assertEqual(VoiceState.LISTENING, get_voice_state())

    def test_tts_failure_is_contained_and_returns_to_listening(self):
        _set_voice_state(VoiceState.THINKING)
        with patch("jarvis.voice_output.get_piper_voice", side_effect=RuntimeError("audio")):
            parler_a_voix_haute("Bonjour")

        self.assertEqual(VoiceState.LISTENING, get_voice_state())

    def test_refuses_to_speak_when_not_thinking(self):
        _set_voice_state(VoiceState.LISTENING)
        with patch("jarvis.voice_output.get_piper_voice", side_effect=self.fail):
            parler_a_voix_haute("Bonjour")

        self.assertEqual(VoiceState.LISTENING, get_voice_state())

    def test_stop_command_is_accent_insensitive(self):
        self.assertTrue(_is_stop_command("Arrête Jarvis"))
        self.assertTrue(_is_stop_command("stop jarvis"))
        self.assertFalse(_is_stop_command("stop jarvis maintenant"))

    def test_stop_command_interrupts_piper_without_pipeline(self):
        _set_voice_state(VoiceState.SPEAKING)
        stopped = []
        fake_sounddevice = SimpleNamespace(
            play=lambda *_args, **_kwargs: None,
            get_stream=lambda: FakePlayback(),
            stop=lambda: stopped.append(True),
        )
        timer = threading.Timer(0.01, demander_arret_tts)
        timer.start()
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}), \
             patch.object(voice_input, "_new_recognizer", return_value=FakeStopRecognizer()):
            _lire_avec_interruption(object(), 22_050)
        timer.join()

        self.assertEqual([True], stopped)
        self.assertEqual(VoiceState.LISTENING, get_voice_state())

    def test_empty_text_in_thinking_goes_to_listening(self):
        _set_voice_state(VoiceState.THINKING)
        parler_a_voix_haute("")
        self.assertEqual(VoiceState.LISTENING, get_voice_state())

