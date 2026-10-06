@echo off
title Phantom Server - The Great Corporation
cd /d "%~dp0"

:: Détection automatique de l'environnement virtuel ou du Python système
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" server\gui_app.py
if errorlevel 1 (
    echo.
    echo [ERREUR] Le serveur Phantom s'est arrete avec un code erreur.
    echo Si des dependances sont manquantes, executez install.ps1 dans PowerShell.
    echo.
    pause
)
