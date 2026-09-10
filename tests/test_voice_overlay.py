"""Tests pour le module voice_overlay."""

import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, patch, MagicMock

from jarvis.voice_state import VoiceState, _set_voice_state, get_voice_state
from jarvis import voice_overlay


class VoiceOverlayTests(unittest.TestCase):
    def setUp(self):
        _set_voice_state(VoiceState.IDLE)
        # Réinitialiser l'état global du module voice_overlay
        voice_overlay._overlay_process = None

    def tearDown(self):
        _set_voice_state(VoiceState.IDLE)
        # Nettoyer l'état global
        voice_overlay._overlay_process = None

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


class VoiceOverlayLifecycleTests(unittest.TestCase):
    """Tests pour le cycle de vie de l'overlay vocal."""

    def setUp(self):
        # Réinitialiser l'état global avant chaque test
        voice_overlay._overlay_process = None

    def tearDown(self):
        # Nettoyer l'état global après chaque test
        voice_overlay._overlay_process = None

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_demarrer_overlay_create_process(self, mock_popen):
        """Test que le démarrage crée bien un processus."""
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll = Mock(return_value=None)  # Processus vivant
        mock_popen.return_value = mock_process

        voice_overlay.demarrer_overlay_vocal()

        # Vérifier que Popen a été appelé
        mock_popen.assert_called_once()
        
        # Vérifier que le processus est stocké
        self.assertIsNotNone(voice_overlay._overlay_process)
        self.assertEqual(voice_overlay._overlay_process.pid, 12345)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_demarrer_overlay_no_duplicate(self, mock_popen):
        """Test qu'un second démarrage ne crée pas un second processus."""
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll = Mock(return_value=None)  # Processus vivant
        mock_popen.return_value = mock_process

        # Premier démarrage
        voice_overlay.demarrer_overlay_vocal()
        first_call_count = mock_popen.call_count

        # Second démarrage (ne devrait pas créer de nouveau processus)
        voice_overlay.demarrer_overlay_vocal()

        # Vérifier que Popen n'a été appelé qu'une seule fois
        self.assertEqual(mock_popen.call_count, first_call_count)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_demarrer_overlay_after_stop(self, mock_popen):
        """Test qu'un redémarrage après arrêt fonctionne."""
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll = Mock(return_value=None)
        mock_popen.return_value = mock_process

        # Premier démarrage
        voice_overlay.demarrer_overlay_vocal()
        first_pid = voice_overlay._overlay_process.pid

        # Simuler l'arrêt (processus terminé)
        voice_overlay._overlay_process.poll = Mock(return_value=123)  # Code de sortie
        
        # Second démarrage (devrait créer un nouveau processus)
        voice_overlay.demarrer_overlay_vocal()
        
        # Vérifier que Popen a été appelé deux fois
        self.assertEqual(mock_popen.call_count, 2)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_arreter_overlay_terminate(self, mock_popen):
        """Test que l'arrêt appelle terminate() sur le processus."""
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll = Mock(return_value=None)  # Processus vivant
        mock_process.wait = Mock(return_value=None)
        mock_popen.return_value = mock_process

        # Démarrer l'overlay
        voice_overlay.demarrer_overlay_vocal()

        # Arrêter l'overlay
        voice_overlay.arreter_overlay_vocal()

        # Vérifier que terminate a été appelé
        mock_process.terminate.assert_called_once()
        
        # Vérifier que wait a été appelé
        mock_process.wait.assert_called_once()
        
        # Vérifier que l'état a été nettoyé
        self.assertIsNone(voice_overlay._overlay_process)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_arreter_overlay_already_dead(self, mock_popen):
        """Test qu'un processus déjà mort est traité proprement."""
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll = Mock(return_value=123)  # Processus déjà mort
        mock_popen.return_value = mock_process

        # Démarrer l'overlay
        voice_overlay.demarrer_overlay_vocal()

        # Arrêter l'overlay (processus déjà mort)
        voice_overlay.arreter_overlay_vocal()

        # Vérifier que terminate n'a PAS été appelé
        mock_process.terminate.assert_not_called()
        
        # Vérifier que l'état a été nettoyé
        self.assertIsNone(voice_overlay._overlay_process)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_arreter_overlay_no_process(self, mock_popen):
        """Test que l'arrêt sans processus ne plante pas."""
        # Arrêter sans avoir démarré
        voice_overlay.arreter_overlay_vocal()

        # Vérifier que Popen n'a pas été appelé
        mock_popen.assert_not_called()
        
        # Vérifier que l'état reste None
        self.assertIsNone(voice_overlay._overlay_process)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_arreter_overlay_timeout_kill(self, mock_popen):
        """Test que l'arrêt force kill après timeout."""
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll = Mock(return_value=None)  # Processus vivant
        
        # Simuler timeout sur wait
        from subprocess import TimeoutExpired
        mock_process.wait = Mock(side_effect=[TimeoutExpired("cmd", 2.0), None])
        mock_popen.return_value = mock_process

        # Démarrer l'overlay
        voice_overlay.demarrer_overlay_vocal()

        # Arrêter l'overlay
        voice_overlay.arreter_overlay_vocal()

        # Vérifier que terminate a été appelé
        mock_process.terminate.assert_called_once()
        
        # Vérifier que kill a été appelé après timeout
        mock_process.kill.assert_called_once()
        
        # Vérifier que l'état a été nettoyé
        self.assertIsNone(voice_overlay._overlay_process)

    @patch('jarvis.voice_overlay.subprocess.Popen')
    def test_demarrer_overlay_exception_handling(self, mock_popen):
        """Test que les exceptions lors du démarrage sont gérées."""
        mock_popen.side_effect = Exception("Erreur de création")

        # Tenter de démarrer - l'exception est propagée
        with self.assertRaises(Exception):
            voice_overlay.demarrer_overlay_vocal()

        # Vérifier que l'état reste None après erreur
        self.assertIsNone(voice_overlay._overlay_process)


if __name__ == "__main__":
    unittest.main()
