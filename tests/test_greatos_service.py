import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import greatos_service


class GreatOSServiceTests(unittest.TestCase):
    @patch("greatos_service.urllib.request.urlopen")
    def test_health_probe_requires_current_api_contract(self, mock_urlopen):
        """tester_reponse_http() retourne True si /jarvis/status repond 200, False sinon."""
        response = MagicMock()
        response.__enter__.return_value = response
        mock_urlopen.return_value = response

        # Cas nominal : HTTP 200 -> pret
        response.status = 200
        self.assertTrue(greatos_service.tester_reponse_http())

        # Cas erreur : HTTP 503 -> pas pret
        response.status = 503
        self.assertFalse(greatos_service.tester_reponse_http())

    @patch("greatos_service.tester_reponse_http", return_value=False)
    def test_wait_for_readiness_stops_when_process_exits(self, _mock_probe):
        process = MagicMock()
        process.poll.return_value = 2

        self.assertFalse(greatos_service._attendre_service_pret(timeout=1, processus=process))

    def test_start_does_not_report_success_when_api_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime_dir = Path(temporary_directory) / "runtime"
            pid_file = runtime_dir / "greatos.pid"
            python_exe = Path(temporary_directory) / "python.exe"
            python_exe.touch()
            process = MagicMock()
            process.pid = 1234
            process.poll.return_value = 2
            process.returncode = 2

            with (
                patch.object(greatos_service, "RUNTIME_DIR", runtime_dir),
                patch.object(greatos_service, "PID_FILE", pid_file),
                patch.object(greatos_service, "VENV_PYTHON", python_exe),
                patch.object(greatos_service, "obtenir_pid_actif", return_value=None),
                patch.object(greatos_service.subprocess, "Popen", return_value=process),
                patch.object(greatos_service, "_attendre_service_pret", return_value=False),
            ):
                self.assertFalse(greatos_service.demarrer_service())

            self.assertFalse(pid_file.exists())


if __name__ == "__main__":
    unittest.main()
