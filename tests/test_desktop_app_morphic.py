"""Tests unitaires pour l'adaptation morphique de l'application desktop Tkinter."""

import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from interface_morphique.app import JarvisGUI, MORPHIC_CONFIG


class TestDesktopAppMorphic(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except Exception:
            self.skipTest("Environnement sans affichage Tkinter")

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_apply_morphic_layout_updates_badge_and_title(self):
        with patch.object(JarvisGUI, "start_proactive_event_stream"):
            gui = JarvisGUI(self.root)

            # 1. Tester le layout focus
            gui.apply_morphic_layout("focus", {"application": "VS Code"})
            self.assertEqual(
                gui.morphic_badge.cget("text"),
                "● FOCUS · VS Code",
            )
            self.assertEqual(
                gui.morphic_badge.cget("fg"),
                MORPHIC_CONFIG["focus"]["color"],
            )
            self.assertIn("Focus", self.root.title())

            # 2. Tester le layout defcon_alert
            gui.apply_morphic_layout("defcon_alert", {})
            self.assertIn("DEFCON", self.root.title())

    def test_handle_event_morphic_layout_changed(self):
        with patch.object(JarvisGUI, "start_proactive_event_stream"):
            gui = JarvisGUI(self.root)
            gui.apply_morphic_layout = MagicMock()

            event = {
                "type": "morphic_layout_changed",
                "data": {
                    "nouveau_layout": "task_runner",
                    "os_context": {"application": "Terminal"},
                },
            }
            gui.handle_event(event)
            gui.apply_morphic_layout.assert_called_once_with("task_runner", {"application": "Terminal"})


if __name__ == "__main__":
    unittest.main()
