import struct
import unittest
from unittest.mock import patch

from capabilities.clap_input import DoubleClapDetector, _maximum_amplitude
from capabilities import clap_input
from core.voice_state import VoiceState, _set_voice_state, get_voice_state


class ClapInputTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)

    def test_two_synthetic_peaks_in_window_form_double_clap(self):
        detector = DoubleClapDetector()
        threshold = clap_input.CLAP_AMPLITUDE_THRESHOLD
        self.assertFalse(detector.process_peak(threshold + 1, 10.0))
        self.assertTrue(detector.process_peak(threshold + 1, 10.4))

    def test_second_peak_outside_window_does_not_trigger(self):
        detector = DoubleClapDetector()
        threshold = clap_input.CLAP_AMPLITUDE_THRESHOLD
        self.assertFalse(detector.process_peak(threshold + 1, 10.0))
        self.assertFalse(detector.process_peak(threshold + 1, 11.0))

    def test_amplitude_uses_absolute_int16_peak(self):
        signal = struct.pack("<hhh", 1, -12_345, 100)
        self.assertEqual(12_345, _maximum_amplitude(signal))

    def test_busy_state_silently_rejects_clap_trigger(self):
        self.assertTrue(_set_voice_state(VoiceState.LISTENING))
        self.assertFalse(_set_voice_state(VoiceState.LISTENING))
        self.assertEqual(VoiceState.LISTENING, get_voice_state())
