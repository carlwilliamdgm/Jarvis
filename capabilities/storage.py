import heapq
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import psutil
from plyer import notification

OS = platform.system()
HOME = Path.home()
DISQUE = str(Path(HOME.anchor))

INTERVALLE = 300
SEUIL_ORANGE = 20
SEUIL_ROUGE = 10
SEUIL_CRITIQUE = 5
AGE_MIN_TEMP_SECONDES = 24 * 60 * 60

DOSSIERS_TEMP = [
    os.environ.get("TEMP", ""),
    os.environ.get("TMP", ""),
    str(Path("C:/Windows/Temp") if OS == "Windows" else Path("/tmp")),
]

DOSSIERS_SCAN_PARTIEL = [str(HOME)]
DOSSIERS_SCAN_COMPLET = [DISQUE]


def get_stockage() -> float:
    usage = psutil.disk_usage(DISQUE)
    return round(100 - usage.percent, 1)


def notifier_windows(titre: str, message: str, urgence: bool = False) -> bool:
    timeout_ms = 30000 if urgence else 10000
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = {json.dumps(str(titre))}
$notify.BalloonTipText = {json.dumps(str(message))}
$notify.Visible = $true
$notify.ShowBalloonTip({timeout_ms})
Start-Sleep -Seconds 1
$notify.Dispose()
"""
    try:
        subprocess.run(
            ["PowerShell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def notifier(titre, message, urgence=False):
    if OS == "Windows":
        notifier_windows(f"Jarvis - {titre}", message, urgence=urgence)
    else:
        try:
            notification.notify(
                title=f"Jarvis - {titre}",
                message=message,
                timeout=10 if not urgence else 30,
            )
        except Exception:
            pass
    print(f"[Jarvis] {titre} : {message}")


def vider_temp() -> str:
    total = 0
    erreurs = 0
    maintenant = time.time()
    for dossier in DOSSIERS_TEMP:
        if not dossier or not os.path.exists(dossier):
            continue
        for item in os.scandir(dossier):
            try:
                if maintenant - item.stat().st_mtime < AGE_MIN_TEMP_SECONDES:
                    continue
                if item.is_file():
                    total += item.stat().st_size
                    os.remove(item.path)
                elif item.is_dir():
                    total += sum(f.stat().st_size for f in Path(item.path).rglob("*") if f.is_file())
                    shutil.rmtree(item.path, ignore_errors=True)
            except OSError:
                erreurs += 1
    detail = f" - {erreurs} element(s) ignores." if erreurs else ""
    return f"Fichiers temporaires anciens vides - {round(total / (1024**2), 1)} MB liberes.{detail}"


def vider_corbeille() -> str:
    try:
        if OS == "Windows":
            subprocess.run(
                ["PowerShell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        elif OS == "Darwin":
            trash = HOME / ".Trash"
            for item in trash.iterdir():
                shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
        else:
            trash = HOME / ".local/share/Trash"
            if trash.exists():
                for item in trash.iterdir():
                    shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
        return "Corbeille videe."
    except Exception as e:
        return f"Erreur lors du vidage de la corbeille : {e}"


def top_fichiers_lourds(n=10, complet=False, max_secondes=15) -> str:
    dossiers = DOSSIERS_SCAN_COMPLET if complet else DOSSIERS_SCAN_PARTIEL
    mode = "complet" if complet else "partiel"
    fichiers = []
    n = max(1, min(int(n), 100))
    max_secondes = max(1, min(int(max_secondes), 120))
    debut = time.time()
    interrompu = False
    for racine in dossiers:
        if not os.path.exists(racine):
            continue
        for root, _, files in os.walk(racine):
            if time.time() - debut > max_secondes:
                interrompu = True
                break
            for f in files:
                try:
                    chemin = os.path.join(root, f)
                    taille = os.path.getsize(chemin)
                    entree = (taille, chemin)
                    if len(fichiers) < n:
                        heapq.heappush(fichiers, entree)
                    elif taille > fichiers[0][0]:
                        heapq.heapreplace(fichiers, entree)
                except OSError:
                    pass
        if interrompu:
            break
    fichiers = sorted(fichiers, reverse=True)
    resultat = f"Top {n} fichiers les plus lourds (scan {mode}) :\n"
    for taille, chemin in fichiers[:n]:
        resultat += f"  {round(taille/1024**2, 1)} MB - {chemin}\n"
    if interrompu:
        resultat += f"Scan interrompu apres {max_secondes} secondes pour conserver la reactivite.\n"
    return resultat


def audit_stockage() -> str:
    usage = psutil.disk_usage(DISQUE)
    libre = round(100 - usage.percent, 1)
    libre_gb = round(usage.free / (1024**3), 1)
    total_gb = round(usage.total / (1024**3), 1)
    etat = "CRITIQUE" if libre <= 5 else "BAS" if libre <= 10 else "MOYEN" if libre <= 20 else "OK"
    return f"Stockage {DISQUE} {libre}% libre - {libre_gb} GB / {total_gb} GB - Etat : {etat}"
