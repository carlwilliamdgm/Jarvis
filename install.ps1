# ==============================================================================
# GreatOS - Script d'Installation Universel (Windows)
# ==============================================================================
# Permet de déployer GreatOS sur n'importe quel ordinateur avec n'importe quel chemin.
# Usage : .\install.ps1

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         INSTALLATION & INITIALISATION DE GREATOS         " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Emplacement : $projectRoot" -ForegroundColor Gray
Write-Host "Utilisateur : $env:USERNAME" -ForegroundColor Gray

# 1. Vérification de Python 3.10+
Write-Host "`n[1/5] Vérification de Python..." -ForegroundColor Yellow
$systemPython = Get-Command "python" -ErrorAction SilentlyContinue
if (-not $systemPython) {
    Write-Host "[ERREUR] Python n'a pas été détecté sur ce système." -ForegroundColor Red
    Write-Host "Veuillez installer Python 3.10 ou supérieur (https://python.org) et cocher 'Add python.exe to PATH'." -ForegroundColor Yellow
    exit 1
}

$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[OK] Python $pyVersion détecté." -ForegroundColor Green

# 2. Création de l'environnement virtuel .venv
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

Write-Host "`n[2/5] Préparation de l'environnement virtuel (.venv)..." -ForegroundColor Yellow
if (-not (Test-Path $venvPython)) {
    Write-Host "Création de l'environnement virtuel..." -ForegroundColor Gray
    & python -m venv $venvDir
    Write-Host "[OK] Environnement virtuel créé." -ForegroundColor Green
} else {
    Write-Host "[OK] Environnement virtuel existant détecté." -ForegroundColor Green
}

# 3. Installation des dépendances
Write-Host "`n[3/5] Installation des dépendances (requirements.txt)..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements.txt") --quiet
Write-Host "[OK] Dépendances installées avec succès." -ForegroundColor Green

# 4. Génération des clés de sécurité souveraines (DataShield AES-256)
Write-Host "`n[4/5] Initialisation de la sécurité DataShield..." -ForegroundColor Yellow
$setupScript = Join-Path $projectRoot "scripts\setup_production.py"
& $venvPython $setupScript

# 5. Enregistrement du service d'arrière-plan (Tâche planifiée)
Write-Host "`n[5/5] Configuration du service résident d'arrière-plan..." -ForegroundColor Yellow
$installServiceScript = Join-Path $projectRoot "scripts\installer_service_windows.ps1"
& powershell.exe -ExecutionPolicy Bypass -File $installServiceScript -DemarrerImmediatement

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "   🎉 Félicitations ! GreatOS est installé et actif !    " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "• Interface Web locale : http://127.0.0.1:8000/web/" -ForegroundColor White
Write-Host "• Pour contrôler le service : python greatos_service.py [status|stop|start|restart]" -ForegroundColor Gray
Write-Host "• Pour lancer les tests : .\.venv\Scripts\python.exe -m pytest tests/ -q" -ForegroundColor Gray
