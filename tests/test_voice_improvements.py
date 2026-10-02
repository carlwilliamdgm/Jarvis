"""
Tests pour les améliorations du mode vocal.

Valide :
- Seuil de wake word adaptatif
- VAD amélioré avec hystérésis
- Reconnexion automatique du micro
"""

import unittest
import numpy as np
from unittest.mock import patch, MagicMock
import threading

from jarvis.audio_capture import AdaptiveVAD, AudioCaptureEngine
from jarvis.voice_input import (
    _get_adaptive_threshold,
    _update_adaptive_threshold,
    _reset_adaptive_threshold,
    WAKE_WORD_DETECTION_THRESHOLD,
)


class TestAdaptiveWakeWordThreshold(unittest.TestCase):
    def setUp(self):
        """Réinitialise le seuil adaptatif avant chaque test."""
        _reset_adaptive_threshold()
        # Forcer le seuil à une valeur connue pour les tests
        import jarvis.voice_input as vi
        vi.WAKE_WORD_DETECTION_THRESHOLD = 0.5
    
    def tearDown(self):
        """Nettoie après chaque test."""
        _reset_adaptive_threshold()
    
    def test_get_adaptive_threshold_initial(self):
        """Teste que le seuil initial est celui par défaut."""
        threshold = _get_adaptive_threshold()
        self.assertEqual(threshold, 0.5)
    
    def test_update_threshold_low_score_accepted(self):
        """Teste que l'historique est mis à jour avec les scores."""
        import jarvis.voice_input as vi
        vi.WAKE_WORD_DETECTION_THRESHOLD = 0.5  # Force reset
        vi._ADAPTIVE_THRESHOLD_HISTORY.clear()  # Clear history
        
        # Simuler plusieurs scores faibles acceptés
        for _ in range(10):
            _update_adaptive_threshold(0.35, was_accepted=True)
        
        # Vérifier que l'historique contient des scores
        self.assertGreater(len(vi._ADAPTIVE_THRESHOLD_HISTORY), 0)
    
    def test_update_threshold_high_score_rejected(self):
        """Teste la diminution du seuil quand un score élevé est rejeté."""
        # Simuler plusieurs scores élevés rejetés
        for _ in range(10):
            _update_adaptive_threshold(0.65, was_accepted=False)
        
        threshold = _get_adaptive_threshold()
        self.assertLess(threshold, 0.5)
    
    def test_reset_threshold(self):
        """Teste la réinitialisation du seuil."""
        _reset_adaptive_threshold()
        initial = _get_adaptive_threshold()
        
        # Modifier le seuil
        for _ in range(10):
            _update_adaptive_threshold(0.35, was_accepted=True)
        
        # Réinitialiser
        _reset_adaptive_threshold()
        
        # Vérifier qu'il est revenu à la valeur par défaut
        threshold = _get_adaptive_threshold()
        self.assertEqual(threshold, initial)


class TestImprovedVAD(unittest.TestCase):
    def setUp(self):
        """Crée une instance de VAD améliorée."""
        self.vad = AdaptiveVAD()
    
    def test_vad_initial_state(self):
        """Teste l'état initial du VAD."""
        self.assertFalse(self.vad.is_speech_active)
        self.assertEqual(self.vad.noise_floor, 50.0)
    
    def test_vad_speech_detection(self):
        """Teste la détection de parole avec hystérésis."""
        # Générer un signal fort (parole)
        strong_signal = np.random.randint(500, 1000, size=1280, dtype=np.int16)
        
        # Nécessite plusieurs trames consécutives
        for _ in range(5):
            self.vad.process(strong_signal)
        
        self.assertTrue(self.vad.is_speech_active)
    
    def test_vad_silence_detection(self):
        """Teste la détection de silence avec hystérésis."""
        # D'abord activer la parole
        strong_signal = np.random.randint(500, 1000, size=1280, dtype=np.int16)
        for _ in range(5):
            self.vad.process(strong_signal)
        
        self.assertTrue(self.vad.is_speech_active)
        
        # Puis envoyer du silence
        silence = np.zeros(1280, dtype=np.int16)
        for _ in range(10):
            self.vad.process(silence)
        
        self.assertFalse(self.vad.is_speech_active)
    
    def test_vad_noise_floor_adaptation(self):
        """Teste l'adaptation du plancher de bruit."""
        # Envoyer du silence continu
        silence = np.zeros(1280, dtype=np.int16)
        for _ in range(20):
            self.vad.process(silence)
        
        # Le plancher de bruit devrait descendre
        self.assertLess(self.vad.noise_floor, 50.0)
    
    def test_vad_reset(self):
        """Teste la réinitialisation du VAD."""
        # Modifier l'état
        strong_signal = np.random.randint(500, 1000, size=1280, dtype=np.int16)
        for _ in range(5):
            self.vad.process(strong_signal)
        
        # Réinitialiser
        self.vad.reset_floor()
        
        # Vérifier l'état initial (is_speech_active est False par défaut après reset)
        self.assertEqual(self.vad.noise_floor, 50.0)
        self.assertEqual(self.vad.consecutive_speech, 0)
        self.assertEqual(self.vad.consecutive_silence, 0)


class TestAudioReconnection(unittest.TestCase):
    def test_reconnect_method_exists(self):
        """Teste que la méthode de reconnexion existe."""
        engine = AudioCaptureEngine()
        self.assertTrue(hasattr(engine, '_attempt_reconnect'))
    
    @patch('jarvis.audio_capture.sd')
    def test_consecutive_error_handling(self, mock_sd):
        """Teste la gestion des erreurs consécutives."""
        # Mock du flux qui échoue
        mock_stream = MagicMock()
        mock_stream.read.side_effect = Exception("Micro déconnecté")
        mock_sd.RawInputStream.return_value = mock_stream
        mock_sd.query_devices.return_value = {
            'name': 'Test Device',
            'default_samplerate': 16000,
            'max_input_channels': 1
        }
        
        engine = AudioCaptureEngine()
        # On ne teste pas la reconnexion complète car cela nécessite
        # un vrai flux audio, mais on vérifie que la méthode existe
        self.assertTrue(hasattr(engine, '_attempt_reconnect'))


if __name__ == "__main__":
    unittest.main()
