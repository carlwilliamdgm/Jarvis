"""Tests unitaires pour le module Desktop Awareness et les primitives universelles de bureau."""

import unittest
from unittest.mock import MagicMock, patch
from context_engine.desktop_awareness import (
    envoyer_signal_multimedia_global,
    redimensionner_ou_deplacer_fenetre,
    obtenir_applications_utilisateur_dynamiques,
    obtenir_contexte_bureau_compact,
)
from taskflow.tools import controler_multimedia_tool, manipuler_fenetre_tool


class TestDesktopAwareness(unittest.TestCase):

    @patch("context_engine.desktop_awareness.user32.keybd_event")
    def test_envoyer_signal_multimedia_pause(self, mock_keybd):
        """Vérifie l'envoi du signal multimédia pause via Win32."""
        res = envoyer_signal_multimedia_global("pause")
        self.assertIn("succès", res.lower())
        self.assertTrue(mock_keybd.called)

    def test_signal_multimedia_action_inconnue(self):
        """Une action multimédia invalide retourne une erreur informative."""
        res = envoyer_signal_multimedia_global("action_imaginaire")
        self.assertIn("Action inconnue", res)

    @patch("context_engine.desktop_awareness.user32.EnumWindows")
    def test_redimensionner_fenetre_introuvable(self, mock_enum):
        """Vérifie le message quand la fenêtre demandée n'existe pas."""
        res = redimensionner_ou_deplacer_fenetre("FenetreInexistante123", 0, 0, 800, 600)
        self.assertIn("Aucune fenêtre", res)

    def test_applications_dynamiques_sans_crash(self):
        """L'inspection dynamique des processus utilisateur ne plante jamais et retourne une liste."""
        apps = obtenir_applications_utilisateur_dynamiques(limite=5)
        self.assertIsInstance(apps, list)

    def test_contexte_bureau_compact_format(self):
        """Le contexte bureau compact retourne une chaîne non vide."""
        ctx = obtenir_contexte_bureau_compact()
        self.assertIsInstance(ctx, str)
        self.assertTrue(len(ctx) > 0)

    @patch("taskflow.tools.envoyer_signal_multimedia_global", return_value="Signal OK")
    def test_controler_multimedia_tool_wrapper(self, mock_signal):
        """Le wrapper d'outil TaskFlow exécute et évalue la capacité."""
        res = controler_multimedia_tool(action="pause")
        self.assertIn("Signal OK", str(res))

    @patch("taskflow.tools.redimensionner_ou_deplacer_fenetre", return_value="Fenêtre OK")
    def test_manipuler_fenetre_tool_wrapper(self, mock_win):
        """Le wrapper d'outil manipuler_fenetre exécute et évalue la capacité."""
        res = manipuler_fenetre_tool(titre="Test", x=0, y=0, largeur=800, hauteur=600)
        self.assertIn("Fenêtre OK", str(res))


if __name__ == "__main__":
    unittest.main()
