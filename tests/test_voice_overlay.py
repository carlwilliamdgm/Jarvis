"""Tests pour le module voice_overlay."""

import threading
import time
import unittest

from core.voice_state import VoiceState, _set_voice_state, get_voice_state


class VoiceOverlayTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)

    def test_get_voice_state_readonly(self):
        """Test que get_voice_state retourne l'état sans effet de bord."""
        initial_state = get_voice_state()
        self.assertEqual(VoiceState.IDLE, initial_state)

        # Appels multiples ne changent pas l'état
        for _ in range(5):
            state = get_voice_state()
            self.assertEqual(VoiceState.IDLE, state)

        # L'état n'a pas été modifié par les lectures
        self.assertEqual(VoiceState.IDLE, get_voice_state())

        # Test avec un état différent
        _set_voice_state(VoiceState.LISTENING)
        self.assertEqual(VoiceState.LISTENING, get_voice_state())

        # Lecture ne modifie pas l'état
        for _ in range(3):
            self.assertEqual(VoiceState.LISTENING, get_voice_state())

        # Vérifier que l'état est toujours LISTENING après les lectures
        self.assertEqual(VoiceState.LISTENING, get_voice_state())


if __name__ == "__main__":
    unittest.main()