"""Tests unitaires pour le module Desktop Vision et la vision multimodale en direct."""

import unittest
from unittest.mock import MagicMock, patch
from context_engine.desktop_vision import (
    attacher_bureau_interactif,
    capturer_ecran_live,
    analyser_ecran_live,
)
from taskflow.tools import regarder_ecran_tool
from core_intellect.intent_router import router_intention, IntentCategory


class TestDesktopVision(unittest.TestCase):

    def test_attacher_bureau_interactif(self):
        """Vérifie que l'attachement à winsta0\\default ne lève pas d'exception."""
        res = attacher_bureau_interactif()
        self.assertIsInstance(res, bool)

    def test_capturer_ecran_live_structure(self):
        """Vérifie la structure du dictionnaire retourné par la capture d'écran."""
        cap = capturer_ecran_live(qualite=50, max_dimension=400)
        self.assertIn("base64", cap)
        self.assertIn("largeur", cap)
        self.assertIn("hauteur", cap)
        self.assertIn("timestamp", cap)
        self.assertGreater(len(cap["base64"]), 100)
        self.assertLessEqual(cap["largeur"], 400)
        self.assertLessEqual(cap["hauteur"], 400)

    @patch("context_engine.desktop_vision.capturer_ecran_live")
    def test_analyser_ecran_live_erreur_capture(self, mock_capture):
        """Si la capture échoue, une erreur propre est retournée."""
        mock_capture.side_effect = RuntimeError("Display disconnected")
        res = analyser_ecran_live("Qu'est-ce que tu vois ?")
        self.assertIn("Impossible de capturer", res)

    @patch("context_engine.desktop_vision.capturer_ecran_live")
    def test_analyser_ecran_live_groq_mock(self, mock_capture):
        """Vérifie l'intégration avec le client vision Groq."""
        mock_capture.return_value = {
            "base64": "dummy_b64",
            "resolution_source": "1920x1080",
            "largeur": 800,
            "hauteur": 600,
            "timestamp": "2026-10-01T12:00:00",
            "zone": "ecran",
        }
        with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
            with patch("groq.Groq") as mock_groq_cls:
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_choice = MagicMock()
                mock_choice.message.content = "Je vois VS Code avec le fichier agent.py ouvert."
                mock_resp.choices = [mock_choice]
                mock_client.chat.completions.create.return_value = mock_resp
                mock_groq_cls.return_value = mock_client

                res = analyser_ecran_live("Que vois-tu ?")
                self.assertIn("VS Code", res)

    @patch("taskflow.tools.analyser_ecran_live", return_value="Écran analysé: terminal PowerShell.")
    def test_regarder_ecran_tool_wrapper(self, mock_vision):
        """Le wrapper d'outil TaskFlow exécute et évalue la capacité."""
        res = regarder_ecran_tool(question="Que vois-tu ?")
        self.assertIn("terminal PowerShell", str(res))

    def test_intent_router_vision_triggers(self):
        """Le routeur d'intention classe les demandes de vision en action avec inventaire d'outils."""
        phrases = [
            "Regarde mon écran s'il te plaît",
            "Tu vois ce message d'erreur ?",
            "Lis ce qui est affiché sur mon écran",
        ]
        for phrase in phrases:
            route = router_intention(phrase)
            self.assertEqual(route.category, IntentCategory.ACTION, f"Échec pour: {phrase}")
            self.assertTrue(route.needs_tool_signatures, f"Outils requis pour: {phrase}")


if __name__ == "__main__":
    unittest.main()
