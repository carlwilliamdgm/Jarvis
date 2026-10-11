@echo off
title J.A.R.V.I.S. - GreatOS
color 0B
echo =======================================================
echo          LANCEMENT DE J.A.R.V.I.S. (GreatOS)
echo =======================================================
echo.
echo Demarrage du moteur GreatOS, du HUD et de l'ecoute vocale...
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "greatos_service.py" restart
    if errorlevel 1 (
        echo.
        echo Erreur : GreatOS n'a pas pu demarrer. Consultez runtime\service.log.
        pause
        exit /b 1
    )
    echo.
    echo GreatOS est pret. Ouverture de l'interface de controle...
    start "" "http://127.0.0.1:8000/web/"
) else (
    echo Erreur : Environnement virtuel introuvable dans .venv !
    pause
    exit /b 1
)
