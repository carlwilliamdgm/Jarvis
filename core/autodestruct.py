import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

try:
    import psutil
except ImportError:
    psutil = None


LOGGER = logging.getLogger("jarvis.autodestruct")

JARVIS_DIR = Path(os.environ.get("JARVIS_INSTALL_DIR", Path(__file__).resolve().parent.parent))
SERVICE_NAME = "JarvisService"
SCHEDULED_TASK_NAMES = ("JarvisAgent", "JarvisAutoUpdate")
OLLAMA_MODEL = "qwen2.5:7b"

MACHINE_ENV_VARS_TO_DELETE = [
    "GIT_PAT_JARVIS",
    "JARVIS_INSTALL_DIR",
    "JARVIS_PYTHON_EXE",
    "JARVIS_PYTHON_ARGS",
    "JARVIS_USER_SITE_PACKAGES",
    "GROQ_API_KEY_1",
    "GROQ_API_KEY_2",
    "GROQ_API_KEY_3",
    "GROQ_API_KEY_4",
    "GROQ_API_KEY_5",
    "OPENROUTER_API_KEY",
]


def schedule_autodestruction(delay_sec: int = 2) -> threading.Thread:
    """Run teardown in a background thread after the caller has answered."""

    def worker() -> None:
        time.sleep(delay_sec)
        perform_autodestruction()

    thread = threading.Thread(target=worker, daemon=True, name="jarvis-autodestruct")
    thread.start()
    return thread


def perform_autodestruction() -> None:
    """Perform local Jarvis teardown, logging each step and never short-circuiting."""
    steps = [
        ("uninstall_windows_service", _uninstall_windows_service),
        ("delete_scheduled_tasks", _delete_scheduled_tasks),
        ("delete_machine_environment", _delete_machine_environment),
        ("remove_ollama_model_if_unused", _remove_ollama_model_if_unused),
        ("delete_jarvis_folder", _delete_jarvis_folder),
    ]

    LOGGER.warning("Jarvis autodestruction started for %s", JARVIS_DIR)
    for step_name, step in steps:
        LOGGER.info("Autodestruction step started: %s", step_name)
        try:
            step()
            LOGGER.info("Autodestruction step completed: %s", step_name)
        except Exception:
            LOGGER.exception("Autodestruction step failed: %s", step_name)
    LOGGER.warning("Jarvis autodestruction finished")


def _run_command(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        LOGGER.warning(
            "Command failed (%s): rc=%s stdout=%r stderr=%r",
            " ".join(command),
            result.returncode,
            result.stdout,
            result.stderr,
        )
    else:
        LOGGER.info("Command succeeded: %s", " ".join(command))
    return result


def _uninstall_windows_service() -> None:
    _run_command(["sc", "stop", SERVICE_NAME])
    _run_command(["sc", "delete", SERVICE_NAME])


def _delete_scheduled_tasks() -> None:
    for task_name in SCHEDULED_TASK_NAMES:
        _run_command(["schtasks", "/Delete", "/TN", task_name, "/F"])


def _delete_machine_environment() -> None:
    if winreg is None:
        LOGGER.warning("Skipping machine environment deletion: winreg unavailable")
        return

    key_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE) as key:
        for var_name in MACHINE_ENV_VARS_TO_DELETE:
            try:
                winreg.DeleteValue(key, var_name)
                LOGGER.info("Deleted machine environment variable: %s", var_name)
            except FileNotFoundError:
                LOGGER.info("Machine environment variable absent: %s", var_name)
            except OSError:
                LOGGER.exception("Failed deleting machine environment variable: %s", var_name)

    _run_command(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "[Environment]::SetEnvironmentVariable('__JARVIS_ENV_REFRESH__', "
                "$null, 'Machine')"
            ),
        ]
    )


def _remove_ollama_model_if_unused() -> None:
    if _other_local_jarvis_installation_running():
        LOGGER.info("Skipping Ollama model removal: another local Jarvis process is running")
        return

    list_result = _run_command(["ollama", "list"], timeout=15)
    if list_result.returncode != 0:
        LOGGER.info("Skipping Ollama model removal: unable to list Ollama models")
        return

    if OLLAMA_MODEL not in list_result.stdout:
        LOGGER.info("Ollama model absent: %s", OLLAMA_MODEL)
        return

    _run_command(["ollama", "rm", OLLAMA_MODEL], timeout=120)


def _other_local_jarvis_installation_running() -> bool:
    if psutil is None:
        LOGGER.info("psutil unavailable; assuming no other local Jarvis process")
        return False

    current_dir = JARVIS_DIR.resolve()
    current_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            if proc.info.get("pid") == current_pid:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if not any(marker in cmdline for marker in ("jarvis.py", "api.server", "server.py", "app.exe")):
                continue
            cwd = proc.info.get("cwd")
            if not cwd:
                LOGGER.info("Found Jarvis-like process without cwd: pid=%s", proc.info.get("pid"))
                return True
            proc_dir = Path(cwd).resolve()
            if proc_dir != current_dir and current_dir not in proc_dir.parents:
                LOGGER.info("Found other local Jarvis process: pid=%s cwd=%s", proc.info.get("pid"), proc_dir)
                return True
        except (psutil.Error, OSError):
            continue
    return False


def _delete_jarvis_folder() -> None:
    jarvis_path = JARVIS_DIR.resolve()
    if not jarvis_path.exists():
        LOGGER.info("Jarvis folder already absent: %s", jarvis_path)
        return
    shutil.rmtree(jarvis_path, ignore_errors=False)
    LOGGER.info("Deleted Jarvis folder: %s", jarvis_path)
