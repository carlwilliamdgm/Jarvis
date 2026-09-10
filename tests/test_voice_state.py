import threading
import unittest

from jarvis.voice_state import VoiceState, _set_voice_state, get_voice_state


class VoiceStateTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)

    def test_listening_is_only_acquired_from_idle(self):
        self.assertTrue(_set_voice_state(VoiceState.LISTENING))
        self.assertFalse(_set_voice_state(VoiceState.LISTENING))
        self.assertEqual(VoiceState.LISTENING, get_voice_state())

    def test_simultaneous_triggers_have_one_winner(self):
        barrier = threading.Barrier(3)
        results = []

        def trigger():
            barrier.wait()
            results.append(_set_voice_state(VoiceState.LISTENING))

        threads = [threading.Thread(target=trigger), threading.Thread(target=trigger)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual([True, False], sorted(results, reverse=True))
        self.assertEqual(VoiceState.LISTENING, get_voice_state())
