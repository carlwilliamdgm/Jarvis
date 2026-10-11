@echo off
title JARVIS - GreatOS Live Daemon
color 0B
echo =======================================================
echo          LANCEMENT DE J.A.R.V.I.S. (GreatOS)
echo =======================================================
echo.
echo Activation de l'environnement virtuel...
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\jarvis_live_daemon.py"
) else (
    echo Erreur : Environnement virtuel introuvable dans .venv !
    pause
)
