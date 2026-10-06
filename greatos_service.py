"""GreatOS Background Resident Service - Gestionnaire de service d'arrière-plan Windows.

Permet à GreatOS de tourner silencieusement en tâche de fond comme une vraie surcouche OS :
- Démarrage sans fenêtre console (CREATE_NO_WINDOW / pythonw)
- Détection dynamique du processus actif (via PID et socket port 8000)
- Monitoring de santé automatique
- Contrôle complet en ligne de commande : start, stop, status, restart
"""

from __future__ import annotations

import os
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


def tester_reponse_http(port: int = PORT_SERVICE) -> bool:
    """Vérifie si GreatOS répond sur l'endpoint de statut."""
    try:
        from datashield.env_loader import charger_environnement
        charger_environnement()
    except Exception:
        pass

    api_key = os.environ.get("JARVIS_API_KEY", "")
    headers = {"User-Agent": "GreatOS-Service-Probe"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        url = f"http://127.0.0.1:{port}/jarvis/status"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status in (200, 401)
    except urllib.error.HTTPError as e:
        # Un code 401 ou 403 signifie que le serveur FastAPI est actif et sécurisé
        return e.code in (200, 401, 403)
    except Exception:
        return False


def obtenir_pid_actif() -> int | None:
    """Retourne le PID du processus GreatOS s'il tourne actuellement."""
    # 1. Vérifier si un processus écoute sur le port 8000 et répond
    pid_port = trouver_processus_sur_port(PORT_SERVICE)
    if pid_port:
        _initialiser_dossiers()
        PID_FILE.write_text(str(pid_port))
        return pid_port

    # 2. Sinon vérifier le fichier PID
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            import psutil
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if "python" in proc.name().lower():
                    return pid
        except Exception:
            pass
    return None


def demarrer_service(silencieux: bool = True) -> bool:
    """Démarre le serveur GreatOS en arrière-plan."""
    _initialiser_dossiers()
    pid = obtenir_pid_actif()
    if pid:
        print(f"[i] GreatOS est déjà actif et opérationnel (PID: {pid}).")
        print(f"     Interface Web : http://127.0.0.1:{PORT_SERVICE}/web/")
        return True

    interp = str(VENV_PYTHON)
    # CREATE_NO_WINDOW (0x08000000) + DETACHED_PROCESS (0x00000008)
    flags = (0x08000000 | 0x00000008) if sys.platform == "win32" and silencieux else 0

    cmd = [
        interp,
        "-m", "uvicorn",
        "interface_morphique.server:app",
        "--host", "127.0.0.1",
        "--port", str(PORT_SERVICE),
        "--log-level", "warning",
    ]

    # Environnement du service : charger .env et désactiver la voix auto
    env = os.environ.copy()
    env["GREATOS_DISABLE_VOICE"] = "1"   # La voix est activée à la demande via l'UI

    log_path = RUNTIME_DIR / "service.log"
    try:
        log_file = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(RACINE),
            creationflags=flags,
            env=env,
            stdout=log_file,
            stderr=log_file,
        )
        PID_FILE.write_text(str(proc.pid))
        
        # Attendre que le serveur démarre (Vosk prend ~6-8s au chargement)
        demarre = False
        for _ in range(30):
            time.sleep(0.5)
            if tester_reponse_http(PORT_SERVICE):
                demarre = True
                break

        if demarre:
            print(f"[OK] GreatOS démarré avec succès en tâche de fond (PID: {proc.pid}).")
            print(f"     Interface Web : http://127.0.0.1:{PORT_SERVICE}/web/")
            return True
        else:
            # Vérifier si le processus est toujours en vie
            import psutil
            if psutil.pid_exists(proc.pid):
                print(f"[OK] GreatOS est en cours d'initialisation (PID: {proc.pid}).")
                print(f"     Interface Web : http://127.0.0.1:{PORT_SERVICE}/web/")
                return True
            print(f"[AVERTISSEMENT] Le serveur n'a pas répondu dans le délai imparti.")
            return False
    except Exception as e:
        print(f"[ERREUR] Échec du démarrage de GreatOS : {e}")
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


def statut_service() -> None:
    """Affiche l'état courant de GreatOS."""
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


if __name__ == "__main__":
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "status"

    if action == "start":
        demarrer_service(silencieux=True)
    elif action == "stop":
        arreter_service()
    elif action == "restart":
        arreter_service()
        time.sleep(1)
        demarrer_service(silencieux=True)
    elif action == "status":
        statut_service()
    else:
        print("Usage: python greatos_service.py [start|stop|restart|status]")
