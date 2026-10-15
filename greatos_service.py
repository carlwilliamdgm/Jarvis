"""GreatOS Background Resident Service - Gestionnaire de service d'arrière-plan Windows.

Permet à GreatOS de tourner silencieusement en tâche de fond comme une vraie surcouche OS :
- Démarrage sans fenêtre console (CREATE_NO_WINDOW / pythonw)
- Détection dynamique du processus actif (via PID et socket port 8000)
- Monitoring de santé automatique
- Contrôle complet en ligne de commande : start, stop, status, restart
"""

from __future__ import annotations

import os
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
import urllib.request

RACINE = Path(__file__).resolve().parent
RUNTIME_DIR = RACINE / "runtime"
PID_FILE = RUNTIME_DIR / "greatos.pid"
VENV_PYTHON = RACINE / ".venv" / "Scripts" / "python.exe"
VENV_PYTHONW = RACINE / ".venv" / "Scripts" / "pythonw.exe"
PORT_SERVICE = 8000


def _initialiser_dossiers():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def trouver_processus_sur_port(port: int = PORT_SERVICE) -> int | None:
    """Retrouve dynamiquement le PID qui écoute sur le port donné."""
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                return conn.pid
    except Exception:
        pass
    return None


def tester_reponse_http(port: int = PORT_SERVICE, timeout: float = 10.0) -> bool:
    """Vérifie que le serveur GreatOS répond correctement sur /jarvis/status.

    Note : le serveur peut mettre jusqu'à 7-10 s pour répondre au premier
    appel (chargement des modèles IA). Le timeout par défaut est donc de 10 s.
    """
    try:
        url = f"http://127.0.0.1:{port}/jarvis/status"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _est_processus_jarvis(pid: int) -> bool:
    """Évite de traiter un PID réutilisé ou un autre service comme GreatOS."""
    import psutil

    try:
        processus = psutil.Process(pid)
        ligne_commande = processus.cmdline()
        cmd_str = " ".join(ligne_commande)
        if "interface_morphique.server:app" not in cmd_str:
            return False
        try:
            dossier = Path(processus.cwd()).resolve()
            return dossier == RACINE.resolve()
        except (psutil.AccessDenied, OSError):
            return True
    except (psutil.Error, OSError):
        return False


def obtenir_pid_actif() -> int | None:
    """Retourne le PID du processus GreatOS s'il tourne actuellement."""
    # 1. Vérifier si un processus écoute sur le port 8000 et répond
    pid_port = trouver_processus_sur_port(PORT_SERVICE)
    if pid_port and _est_processus_jarvis(pid_port):
        _initialiser_dossiers()
        PID_FILE.write_text(str(pid_port))
        return pid_port

    # 2. Sinon vérifier le fichier PID
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if _est_processus_jarvis(pid):
                return pid
        except Exception:
            pass
        PID_FILE.unlink(missing_ok=True)
    return None


def _attendre_service_pret(timeout: float, processus: subprocess.Popen | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if tester_reponse_http(timeout=min(1.0, remaining)):
            return True
        if processus is not None and processus.poll() is not None:
            return False
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))


def demarrer_service(silencieux: bool = True) -> bool:
    """Démarre le serveur GreatOS en arrière-plan."""
    _initialiser_dossiers()
    pid = obtenir_pid_actif()
    if pid:
        if tester_reponse_http():
            print(f"[i] GreatOS est déjà actif et opérationnel (PID: {pid}).")
            print(f"     Interface Web : http://127.0.0.1:{PORT_SERVICE}/web/")
            return True
        print(f"[ATTENTE] GreatOS existe (PID: {pid}), mais son API ne répond pas encore.")
        if _attendre_service_pret(timeout=15):
            return True
        print(f"[ERREUR] GreatOS n'est pas prêt. Consultez {RUNTIME_DIR / 'service.log'}.")
        return False

    interp = str(VENV_PYTHONW if (silencieux and VENV_PYTHONW.is_file()) else VENV_PYTHON)
    if not Path(interp).is_file():
        interp = str(VENV_PYTHON)
    if not Path(interp).is_file():
        print(f"[ERREUR] Python de l'environnement GreatOS introuvable : {interp}")
        return False

    # CREATE_NEW_PROCESS_GROUP (0x00000200) pour détacher le groupe de processus sous Windows
    flags = 0x00000200 if sys.platform == "win32" else 0

    cmd = [
        interp,
        "-m", "uvicorn",
        "interface_morphique.server:app",
        "--host", "127.0.0.1",
        "--port", str(PORT_SERVICE),
        "--log-level", "info",
    ]

    # Le service lancé par l'utilisateur doit activer l'écoute vocale dès son
    # démarrage. L'API démarre également le HUD et le moteur voice_input officiel.
    env = os.environ.copy()
    env["GREATOS_DISABLE_VOICE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"

    log_path = RUNTIME_DIR / "service.log"
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(RACINE),
                creationflags=flags,
                env=env,
                stdout=log_file,
                stderr=log_file,
            )
        PID_FILE.write_text(str(proc.pid))

        if _attendre_service_pret(timeout=30, processus=proc):
            print(f"[OK] GreatOS démarré avec succès en tâche de fond (PID: {proc.pid}).")
            print(f"     Interface Web : http://127.0.0.1:{PORT_SERVICE}/web/")
            return True

        if proc.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            print(
                f"[ERREUR] Le serveur s'est arrêté avant de répondre "
                f"(code {proc.returncode}). Consultez {log_path}."
            )
        else:
            print(
                f"[ERREUR] Le serveur n'a pas répondu dans les 30 secondes. "
                f"Consultez {log_path}."
            )
        return False
    except Exception as e:
        print(f"[ERREUR] Échec du démarrage de GreatOS : {e}. Consultez {log_path}.")
        return False


def arreter_service() -> bool:
    """Arrête proprement le processus GreatOS résident."""
    pid = obtenir_pid_actif()
    if not pid:
        print("[i] Aucun service GreatOS actif à arrêter.")
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
        return True

    try:
        import psutil
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.terminate()
        parent.terminate()
        parent.wait(timeout=3)
        PID_FILE.unlink(missing_ok=True)
        print(f"[OK] GreatOS (PID {pid}) arrêté proprement.")
        return True
    except Exception as e:
        try:
            os.kill(pid, signal.SIGTERM)
            PID_FILE.unlink(missing_ok=True)
            print(f"[OK] GreatOS (PID {pid}) arrêté.")
            return True
        except Exception:
            print(f"[ERREUR] Impossible d'arrêter le processus {pid} : {e}")
            return False


def statut_service() -> bool:
    """Affiche l'état courant de GreatOS et indique si l'API est prête."""
    pid = obtenir_pid_actif()
    repond = tester_reponse_http(PORT_SERVICE)
    if repond:
        info_pid = f" (PID: {pid})" if pid else ""
        print(f"[ACTIF] GreatOS est en ligne et répond{info_pid}.")
        print(f"        Accès Web : http://127.0.0.1:{PORT_SERVICE}/web/")
    elif pid:
        print(f"[ATTENTE] Processus GreatOS actif (PID: {pid}), port en initialisation...")
    else:
        print("[INACTIF] GreatOS est arrêté.")
    return repond


def main() -> int:
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "status"

    if action == "start":
        return 0 if demarrer_service(silencieux=True) else 1
    elif action == "stop":
        return 0 if arreter_service() else 1
    elif action == "restart":
        if not arreter_service():
            return 1
        time.sleep(1)
        return 0 if demarrer_service(silencieux=True) else 1
    elif action == "status":
        return 0 if statut_service() else 1
    else:
        print("Usage: python greatos_service.py [start|stop|restart|status]")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
