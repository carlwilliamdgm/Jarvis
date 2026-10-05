@echo off
setlocal EnableDelayedExpansion
title Installation GreatOS Jarvis

:: ── Verification des privileges Administrateur ──────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Demande d'elevation Administrateur...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: ── Mode Administrateur actif ───────────────────────────────────────
cd /d "%~dp0"
cls
echo ===================================================================
echo               INSTALLATION AUTOMATISEE GREATOS JARVIS
echo ===================================================================
echo.
echo Ce programme installe et configure GreatOS Jarvis de maniere autonome.
echo.

:: 1. Si bootstrap\install.ps1 est deja present dans ce dossier
if exist "%~dp0bootstrap\install.ps1" (
    :: Verification si un PAT est deja enregistre au niveau Machine
    for /f "tokens=*" %%a in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable('GIT_PAT_JARVIS', 'Machine')"') do set "EXISTING_PAT=%%a"
    
    if not "!EXISTING_PAT!"=="" (
        echo [OK] Personal Access Token GitHub detecte.
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap\install.ps1" -GitHubPAT "!EXISTING_PAT!"
    ) else (
        echo Entrez votre Personal Access Token GitHub (scope: repo sur carlwilliamdgm/Jarvis) :
        set /p "USER_PAT=PAT: "
        if "!USER_PAT!"=="" (
            echo [ERREUR] Le PAT est obligatoire pour synchroniser le projet.
            pause
            exit /b 1
        )
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap\install.ps1" -GitHubPAT "!USER_PAT!"
    )
    goto :fin
)

:: 2. Si on est en installation publique minimale (install_public.ps1)
if exist "%~dp0install_public.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_public.ps1"
    goto :fin
)

echo [ERREUR] Aucun script d'installation trouve dans ce dossier.
pause
exit /b 1

:fin
echo.
echo ===================================================================
echo Installation terminee ! Appuyez sur une touche pour quitter.
echo ===================================================================
pause >nul
