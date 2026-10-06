"""Tests unitaires pour le module context_engine/os_hooks.py."""

import sys
import unittest
from unittest.mock import MagicMock, patch

from context_engine.os_hooks import OSHookManager, get_os_hook_manager


class TestOSHooks(unittest.TestCase):
    def setUp(self):
        self.manager = OSHookManager()

    def test_get_current_context_initial(self):
        ctx = self.manager.get_current_context()
        self.assertEqual(ctx["application"], "Inconnue")
        self.assertEqual(ctx["pid"], 0)

    @patch("ctypes.windll.user32")
    def test_analyser_fenetre_mock(self, mock_user32):
        if sys.platform != "win32":
            self.skipTest("Windows uniquement")

        # Configurer les retours de l'API Win32
        mock_user32.GetWindowTextLengthW.return_value = 10
        mock_user32.GetSystemMetrics.side_effect = [1920, 1080]

        def fake_get_pid(hwnd, byref_pid):
            byref_pid._obj.value = 1234
            return 1

        mock_user32.GetWindowThreadProcessId.side_effect = fake_get_pid

        # Simuler analyse de fenêtre avec succès
        with patch("psutil.Process") as mock_proc:
            mock_p = MagicMock()
            mock_p.name.return_value = "Code.exe"
            mock_p.exe.return_value = "C:\\Program Files\\VSCode\\Code.exe"
            mock_proc.return_value = mock_p

            res = self.manager._analyser_fenetre(12345)
            self.assertEqual(res["hwnd"], 12345)
            self.assertEqual(res["processus"], "Code.exe")
            self.assertEqual(res["pid"], 1234)

    def test_subscription_callback(self):
        notified = []

        def callback(info):
            notified.append(info)

        self.manager.abonner_changement_contexte(callback)
        self.assertEqual(len(self.manager._subscribers), 1)

        # Simuler un événement _on_winevent avec mock analyse
        fake_info = {
            "hwnd": 999,
            "titre": "Document.txt - Notepad",
            "application": "Bloc-notes",
            "processus": "notepad.exe",
            "pid": 456,
            "plein_ecran": False,
            "timestamp": 123.4,
        }
        with patch.object(self.manager, "_analyser_fenetre", return_value=fake_info):
            with patch("context_engine.os_hooks.get_event_bus") as mock_bus:
                mock_bus_inst = MagicMock()
                mock_bus.return_value = mock_bus_inst

                # Appeler callback WinEvent (EVENT_SYSTEM_FOREGROUND = 0x0003)
                self.manager._on_winevent(None, 0x0003, 999, 0, 0, 0, 0)

                self.assertEqual(len(notified), 1)
                self.assertEqual(notified[0]["application"], "Bloc-notes")
                mock_bus_inst.emit_broadcast.assert_called_once_with("os_context_changed", fake_info)

    def test_singleton(self):
        m1 = get_os_hook_manager()
        m2 = get_os_hook_manager()
        self.assertIs(m1, m2)


if __name__ == "__main__":
    unittest.main()
