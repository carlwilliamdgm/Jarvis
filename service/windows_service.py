import os
import sys

JARVIS_DIR = r"C:\Users\Carl\Jarvis"
SERVICE_DIR = os.path.join(JARVIS_DIR, "service")
PYTHON_EXE = r"C:\Program Files\Python312\python.exe"
USER_SITE_PACKAGES = r"C:\Users\Carl\AppData\Roaming\Python\Python312\site-packages"
LOG_PATH = os.path.join(SERVICE_DIR, "jarvis_service.log")
UVICORN_LOG_PATH = os.path.join(SERVICE_DIR, "uvicorn.log")

if USER_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, USER_SITE_PACKAGES)

import logging
import subprocess
import threading

import win32event
import win32service
import win32serviceutil

os.makedirs(SERVICE_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("JarvisService")


class JarvisService(win32serviceutil.ServiceFramework):
    _svc_name_ = "JarvisService"
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
            os.chdir(JARVIS_DIR)
            if JARVIS_DIR not in sys.path:
                sys.path.insert(0, JARVIS_DIR)
            import site

            sys.path.insert(0, r"C:\Users\Carl\AppData\Roaming\Python\Python312\site-packages")

            env = os.environ.copy()
            env["PYTHONPATH"] = r"C:\Users\Carl\AppData\Roaming\Python\Python312\site-packages"

            self.uvicorn_log = open(os.path.join(JARVIS_DIR, "service", "uvicorn.log"), "w")
            self.process = subprocess.Popen(
                [
                    PYTHON_EXE,
                    "-m",
                    "uvicorn",
                    "api.server:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                ],
                cwd=JARVIS_DIR,
                env=env,
                stdout=self.uvicorn_log,
                stderr=subprocess.STDOUT,
            )
            log.info("uvicorn started, PID=%s.", self.process.pid)
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        except Exception:
            log.exception("Service failed to start.")
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)
            self._close_uvicorn_log()
            return

        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        self._close_uvicorn_log()
        log.info("Service stopped.")

    def _close_uvicorn_log(self):
        if self.uvicorn_log:
            try:
                self.uvicorn_log.close()
            except Exception:
                log.exception("Failed to close uvicorn log file.")
            finally:
                self.uvicorn_log = None


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(JarvisService)
