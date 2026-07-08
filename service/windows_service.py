import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Force UTF-8 encoding to avoid charmap errors on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

SERVICE_NAME = "JarvisService"


def _fallback_log_dir():
    base_dir = os.environ.get("ProgramData") or tempfile.gettempdir()
    return os.path.join(base_dir, "Jarvis")


def _resolve_jarvis_dir():
    env_value = os.environ.get("JARVIS_INSTALL_DIR")
    if env_value:
        return env_value
    return str(Path(__file__).resolve().parents[1])


def _ensure_log_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        fallback_dir = _fallback_log_dir()
        os.makedirs(fallback_dir, exist_ok=True)
        return fallback_dir


def _resolve_python_exe():
    env_value = os.environ.get("JARVIS_PYTHON_EXE")
    if env_value:
        return env_value

    candidates = []
    base_executable = getattr(sys, "_base_executable", None)
    if base_executable:
        candidates.append(base_executable)

    current_executable = sys.executable
    if current_executable:
        candidates.append(current_executable)
        if Path(current_executable).name.lower() == "pythonservice.exe":
            candidates.append(str(Path(current_executable).with_name("python.exe")))

    for candidate in candidates:
        if candidate and Path(candidate).name.lower() != "pythonservice.exe" and Path(candidate).is_file():
            return candidate

    return current_executable


JARVIS_DIR = _resolve_jarvis_dir()
SERVICE_DIR = os.path.join(JARVIS_DIR, "service")
LOG_DIR = _ensure_log_dir(SERVICE_DIR)
PYTHON_EXE = _resolve_python_exe()
PYTHON_ARGS_RAW = os.environ.get("JARVIS_PYTHON_ARGS", "")
PYTHON_ARGS = PYTHON_ARGS_RAW.split()
PYTHON_COMMAND = [PYTHON_EXE] + PYTHON_ARGS
USER_SITE_PACKAGES = os.environ.get("JARVIS_USER_SITE_PACKAGES")
LOG_PATH = os.path.join(LOG_DIR, "jarvis_service.log")
UVICORN_LOG_PATH = os.path.join(LOG_DIR, "uvicorn.log")

if USER_SITE_PACKAGES and USER_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, USER_SITE_PACKAGES)

import logging
import subprocess
import threading

import win32event
import win32service
import win32serviceutil

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(SERVICE_NAME)
log.info("Service module loaded.")
log.info(
    "Environment: JARVIS_INSTALL_DIR=%r, JARVIS_PYTHON_EXE=%r, "
    "JARVIS_PYTHON_ARGS=%r, JARVIS_USER_SITE_PACKAGES=%r.",
    os.environ.get("JARVIS_INSTALL_DIR"),
    os.environ.get("JARVIS_PYTHON_EXE"),
    PYTHON_ARGS_RAW,
    USER_SITE_PACKAGES,
)
log.info(
    "Resolved paths: __file__=%r, JARVIS_DIR=%r, SERVICE_DIR=%r, "
    "LOG_PATH=%r, UVICORN_LOG_PATH=%r.",
    __file__,
    JARVIS_DIR,
    SERVICE_DIR,
    LOG_PATH,
    UVICORN_LOG_PATH,
)
log.info("Python command: %r.", PYTHON_COMMAND)


class JarvisService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = "Jarvis AI Agent"
    _svc_description_ = "Runs the Jarvis FastAPI service with uvicorn."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.stop_event = threading.Event()
        self.process = None
        self.uvicorn_log = None

    def SvcStop(self):
        log.info("Stop requested.")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()

        if self.process and self.process.poll() is None:
            try:
                log.info("Terminating uvicorn process, PID=%s.", self.process.pid)
                self.process.terminate()
                self.process.wait(timeout=20)
                log.info("uvicorn process terminated.")
            except subprocess.TimeoutExpired:
                log.warning("uvicorn did not stop in time; killing process.")
                self.process.kill()
                self.process.wait(timeout=10)
            except Exception:
                log.exception("Failed to stop uvicorn process.")

        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        log.info("Service starting.")
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

        try:
            log.info("Changing working directory to %r.", JARVIS_DIR)
            os.chdir(JARVIS_DIR)
            if JARVIS_DIR not in sys.path:
                log.info("Adding JARVIS_DIR to sys.path.")
                sys.path.insert(0, JARVIS_DIR)
            if USER_SITE_PACKAGES and USER_SITE_PACKAGES not in sys.path:
                log.info("Adding JARVIS_USER_SITE_PACKAGES to sys.path: %r.", USER_SITE_PACKAGES)
                sys.path.insert(0, USER_SITE_PACKAGES)

            env = os.environ.copy()
            python_path = [JARVIS_DIR]
            if USER_SITE_PACKAGES:
                python_path.append(USER_SITE_PACKAGES)
            existing_pythonpath = env.get("PYTHONPATH")
            if existing_pythonpath:
                python_path.append(existing_pythonpath)
            env["PYTHONPATH"] = os.pathsep.join(python_path)
            log.info("Prepared PYTHONPATH=%r.", env["PYTHONPATH"])

            log.info("Opening uvicorn log at %r.", UVICORN_LOG_PATH)
            self.uvicorn_log = open(UVICORN_LOG_PATH, "w")
            command = PYTHON_COMMAND + [
                "-m",
                "uvicorn",
                "api.server:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ]
            log.info("Starting uvicorn command=%r cwd=%r.", command, JARVIS_DIR)
            self.process = subprocess.Popen(
                command,
                cwd=JARVIS_DIR,
                env=env,
                stdout=self.uvicorn_log,
                stderr=subprocess.STDOUT,
            )
            log.info("uvicorn started, PID=%s.", self.process.pid)
            time.sleep(2)
            exit_code = self.process.poll()
            if exit_code is not None:
                log.error("uvicorn exited during startup with code %s.", exit_code)
                self._close_uvicorn_log()
                log.error("uvicorn log tail:\n%s", self._read_uvicorn_log_tail())
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return

            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        except Exception:
            log.error("Service failed to start:\n%s", traceback.format_exc())
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)
            self._close_uvicorn_log()
            return

        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        self._close_uvicorn_log()
        log.info("Service stopped.")

    def _read_uvicorn_log_tail(self, max_chars=8000):
        try:
            with open(UVICORN_LOG_PATH, "r", encoding="utf-8", errors="replace") as log_file:
                content = log_file.read()
            return content[-max_chars:] if content else "<empty uvicorn log>"
        except Exception:
            return "Failed to read uvicorn log:\n%s" % traceback.format_exc()

    def _close_uvicorn_log(self):
        if self.uvicorn_log:
            try:
                self.uvicorn_log.close()
            except Exception:
                log.error("Failed to close uvicorn log file:\n%s", traceback.format_exc())
            finally:
                self.uvicorn_log = None


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(JarvisService)
