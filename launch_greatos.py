#!/usr/bin/env python
"""Launcher principal GreatOS — démarre le serveur, le systray et le HUD.

Usage :
    python launch_greatos.py            # Démarrage complet
    python launch_greatos.py --no-hud   # Sans ouvrir le HUD au démarrage
    python launch_greatos.py --no-tray  # Sans icône dans la barre des tâches
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PORT = 8000
_URL_STATUS = f"http://127.0.0.1:{PORT}/hud"
_URL_HUD = f"http://127.0.0.1:{PORT}/hud"


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def serveur_actif(timeout: float = 2.0) -> bool:
    """Retourne True si le serveur HTTP répond."""
    try:
        with urllib.request.urlopen(_URL_STATUS, timeout=timeout) as resp:
            return resp.status in (200, 423)
    except urllib.error.HTTPError as err:
        return err.code in (200, 423)
    except Exception:
        return False


def demarrer_serveur() -> subprocess.Popen:
    """Lance le serveur FastAPI en sous-processus."""
    cmd = [
        str(PYTHON), "-m", "uvicorn", "interface_morphique.server:app",
        "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning",
    ]
    # CREATE_NO_WINDOW = 0x08000000 — pas de fenêtre console parasite
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000
    return subprocess.Popen(cmd, cwd=str(ROOT), **kwargs)


def attendre_serveur(timeout: float = 20.0, proc: subprocess.Popen | None = None) -> bool:
    """Attend jusqu'à `timeout` secondes que le serveur soit prêt.

    Retourne True si le serveur répond, False si timeout atteint.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            print(f"[GreatOS] ERREUR : le serveur s'est arrêté prématurément (code {proc.returncode})",
                  file=sys.stderr)
            return False
        if serveur_actif(timeout=0.5):
            return True
        time.sleep(0.5)
    return False


def _trouver_edge_ou_chrome() -> str | None:
    """Retourne le chemin vers msedge.exe ou chrome.exe, ou None."""
    candidats = [
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((c for c in candidats if c and Path(c).is_file()), None)


def ouvrir_hud() -> None:
    """Ouvre le HUD dans Edge/Chrome en mode --app (fenêtre dédiée sans chrome de navigateur)."""
    exe = _trouver_edge_ou_chrome()
    if exe:
        subprocess.Popen([exe, f"--app={_URL_HUD}"])
        print(f"[GreatOS] HUD ouvert dans {Path(exe).name} (--app mode)")
    else:
        import webbrowser
        webbrowser.open(_URL_HUD)
        print("[GreatOS] HUD ouvert dans le navigateur par défaut")


def demarrer_tray() -> threading.Thread | None:
    """Lance l'icône système dans un thread daemon.

    Retourne le thread ou None si l'import échoue.
    """
    try:
        from interface_morphique.tray_icon import demarrer_tray as _tray_fn  # type: ignore
        t = threading.Thread(target=_tray_fn, name="greatos-tray", daemon=True)
        t.start()
        return t
    except ImportError:
        print("[GreatOS] AVERTISSEMENT : tray_icon non disponible (pystray manquant ?)", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Launcher GreatOS")
    parser.add_argument("--no-hud", action="store_true", help="Ne pas ouvrir le HUD au démarrage")
    parser.add_argument("--no-tray", action="store_true", help="Ne pas afficher l'icône dans la barre des tâches")
    args = parser.parse_args()

    proc_serveur: subprocess.Popen | None = None

    # --- Démarrer le serveur si nécessaire ---
    if serveur_actif():
        print(f"[GreatOS] Serveur déjà actif sur le port {PORT}.")
    else:
        print(f"[GreatOS] Démarrage du serveur sur le port {PORT}...")
        proc_serveur = demarrer_serveur()
        if not attendre_serveur(timeout=20.0, proc=proc_serveur):
            print("[GreatOS] ERREUR : impossible de démarrer le serveur dans les 20 secondes.", file=sys.stderr)
            if proc_serveur and proc_serveur.poll() is None:
                proc_serveur.terminate()
            return 1
        print("[GreatOS] Serveur prêt ✓")

    # --- System tray ---
    if not args.no_tray:
        tray_thread = demarrer_tray()
        if tray_thread:
            print("[GreatOS] Icône système démarrée ✓")

    # --- HUD ---
    if not args.no_hud:
        ouvrir_hud()

    print("[GreatOS] GreatOS est opérationnel. Appuyez sur Ctrl+C pour arrêter.")

    # --- Garder le processus en vie si on a démarré le serveur ---
    if proc_serveur is not None:
        try:
            proc_serveur.wait()
        except KeyboardInterrupt:
            print("\n[GreatOS] Arrêt demandé...")
            proc_serveur.terminate()
            try:
                proc_serveur.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc_serveur.kill()
        return proc_serveur.returncode or 0
    else:
        # Serveur existant : juste attendre Ctrl+C
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[GreatOS] Au revoir.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
