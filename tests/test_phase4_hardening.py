import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    import pytest
except ImportError:
    class _MarkStub:
        def __getattr__(self, name):
            def _decorator(*args, **kwargs):
                if len(args) == 1 and callable(args[0]) and not kwargs:
                    return args[0]
                return lambda f: f
            return _decorator
    class _PytestStub:
        mark = _MarkStub()
    pytest = _PytestStub()  # type: ignore[assignment]

import core.autodestruct as autodestruct
import service.windows_service as windows_service


@pytest.mark.smoke
class TestPhase4Hardening(unittest.TestCase):
    """Tests for Phase 4 hardening, logs rotation, and autodestruct safety."""

    def test_is_admin_check(self):
        """Test is_admin returns a boolean without raising exceptions."""
        result = autodestruct.is_admin()
        self.assertIsInstance(result, bool)

    @patch("core.autodestruct.is_admin", return_value=False)
    @patch("core.autodestruct.winreg")
    def test_delete_machine_env_skips_when_not_admin(self, mock_winreg, mock_is_admin):
        """Test _delete_machine_environment safely skips HKLM without error when non-admin."""
        with self.assertLogs("jarvis.autodestruct", level="WARNING") as cm:
            autodestruct._delete_machine_environment()
        self.assertTrue(any("process lacks administrative elevation" in msg for msg in cm.output))
        mock_winreg.OpenKey.assert_not_called()

    @patch("core.autodestruct.is_admin", return_value=True)
    @patch("core.autodestruct.winreg")
    @patch("core.autodestruct._run_command")
    def test_delete_machine_env_executes_when_admin(self, mock_run_cmd, mock_winreg, mock_is_admin):
        """Test _delete_machine_environment deletes HKLM keys when admin."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
        mock_winreg.HKEY_LOCAL_MACHINE = 123
        mock_winreg.KEY_SET_VALUE = 456

        autodestruct._delete_machine_environment()
        self.assertTrue(mock_winreg.DeleteValue.called)

    @patch("core.autodestruct.subprocess.Popen")
    @patch("core.autodestruct.os.path.exists", return_value=True)
    def test_delete_jarvis_folder_spawns_detached_process(self, mock_exists, mock_popen):
        """Test _delete_jarvis_folder detaches a PowerShell process to remove folder."""
        autodestruct._delete_jarvis_folder()
        self.assertTrue(mock_popen.called)
        call_args, call_kwargs = mock_popen.call_args
        self.assertEqual(call_args[0][0], "powershell")
        self.assertIn("Wait-Process", call_args[0][5])
        self.assertIn("Remove-Item", call_args[0][5])
        if sys.platform == "win32":
            expected_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            self.assertEqual(call_kwargs.get("creationflags"), expected_flags)

    def test_service_rotating_file_handlers_configuration(self):
        """Test service log and uvicorn log handlers are configured with 10MB and 5 backups."""
        self.assertEqual(windows_service.service_handler.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(windows_service.service_handler.backupCount, 5)

        self.assertEqual(windows_service.uvicorn_handler.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(windows_service.uvicorn_handler.backupCount, 5)


if __name__ == "__main__":
    unittest.main()
