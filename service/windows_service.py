import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

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
from logging.handlers import RotatingFileHandler
import subprocess
import threading

# Safely import win32 modules; fallback to dummy on failure
try:
    import win32event
    import win32service
    import win32serviceutil
    _WIN32_AVAILABLE = True
except Exception:  # pragma: no cover
    _WIN32_AVAILABLE = False

    # Dummy event module with required functions
    class _DummyWin32Event:
        @staticmethod
        def CreateEvent(*args, **kwargs):
            return None

        @staticmethod
        def SetEvent(event):
            pass

    # Dummy service constants
    class _DummyWin32Service:
        SERVICE_STOP_PENDING = 0
        SERVICE_START_PENDING = 0

    # Dummy ServiceFramework base class
    class _DummyServiceFramework:
        def __init__(self, args):
            pass

        def ReportServiceStatus(self, status):
            pass

    # Assign dummy modules/objects
    win32event = _DummyWin32Event()
    win32service = _DummyWin32Service()
    win32serviceutil = type('win32serviceutil', (), {'ServiceFramework': _DummyServiceFramework})


# Service logger with RotatingFileHandler (max 10MB, 5 backups)
service_handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
service_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

log = logging.getLogger(SERVICE_NAME)
log.setLevel(logging.INFO)
log.addHandler(service_handler)
log.propagate = False

# Uvicorn pipe logger with RotatingFileHandler (max 10MB, 5 backups)
uvicorn_handler = RotatingFileHandler(
    UVICORN_LOG_PATH,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
uvicorn_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
uvicorn_log = logging.getLogger("jarvis.service.uvicorn")
uvicorn_log.setLevel(logging.INFO)
uvicorn_log.addHandler(uvicorn_handler)
uvicorn_log.propagate = False

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
        self.pump_thread = None

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

        self._close_uvicorn_log()
        win32event.SetEvent(self.hWaitStop)

    def _pipe_reader(self, process_stdout):
        try:
            for line in iter(process_stdout.readline, b""):
                if not line:
                    break
                decoded_line = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if decoded_line:
                    uvicorn_log.info(decoded_line)
                if self.stop_event.is_set() and (self.process and self.process.poll() is not None):
                    break
        except Exception:
            log.exception("Error while streaming uvicorn logs.")
        finally:
            try:
                process_stdout.close()
            except Exception:
                pass

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

            log.info("Configured rotating uvicorn log handler at %r (max 10MB, 5 backups).", UVICORN_LOG_PATH)
            command = PYTHON_COMMAND + [
                "-m",
                "uvicorn",
                "interface_morphique.server:app",
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
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            log.info("uvicorn started, PID=%s.", self.process.pid)

            # Start background pipe streaming thread to RotatingFileHandler
            self.pump_thread = threading.Thread(
                target=self._pipe_reader,
                args=(self.process.stdout,),
                daemon=True,
                name="UvicornLogPump",
            )
            self.pump_thread.start()

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
            if not os.path.exists(UVICORN_LOG_PATH):
                return "<empty uvicorn log>"
            with open(UVICORN_LOG_PATH, "r", encoding="utf-8", errors="replace") as log_file:
                content = log_file.read()
            return content[-max_chars:] if content else "<empty uvicorn log>"
        except Exception:
            return "Failed to read uvicorn log:\n%s" % traceback.format_exc()

    def _close_uvicorn_log(self):
        try:
            uvicorn_handler.flush()
            service_handler.flush()
        except Exception:
            pass


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(JarvisService)
