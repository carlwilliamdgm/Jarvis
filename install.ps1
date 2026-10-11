# ==============================================================================
# GreatOS - Script d'Installation Universel (Windows)
# ==============================================================================
# Permet de déployer GreatOS sur n'importe quel ordinateur avec n'importe quel chemin.
# Usage : .\install.ps1

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    & $Executable @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Operation a échoué (code de sortie $exitCode)."
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         INSTALLATION & INITIALISATION DE GREATOS         " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Emplacement : $projectRoot" -ForegroundColor Gray
Write-Host "Utilisateur : $env:USERNAME" -ForegroundColor Gray

# 1. Vérification de Python 3.12
Write-Host "`n[1/5] Vérification de Python..." -ForegroundColor Yellow
$pythonExe = $null
$pythonLauncher = Get-Command "py" -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    $resolvedPython = & $pythonLauncher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $resolvedPython) {
        $resolvedPython = $resolvedPython.Trim()
        if (Test-Path $resolvedPython) {
            $pythonExe = $resolvedPython
        }
    }
}

$systemPython = Get-Command "python" -ErrorAction SilentlyContinue
if (-not $pythonExe -and $systemPython) {
    $pythonExe = $systemPython.Source
}
if (-not $pythonExe) {
    throw "Python 3.12 est introuvable. Installez Python 3.12 depuis https://python.org, puis relancez l'installation."
}

$pyVersion = [string](& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ($LASTEXITCODE -ne 0 -or -not $pyVersion -or $pyVersion.Trim() -ne "3.12") {
    $detectedVersion = if ($pyVersion) { $pyVersion.Trim() } else { "indisponible" }
    throw "GreatOS nécessite Python 3.12 (version détectée : $detectedVersion)."
}
Write-Host "[OK] Python $pyVersion détecté." -ForegroundColor Green

# 2. Création de l'environnement virtuel .venv
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

Write-Host "`n[2/5] Préparation de l'environnement virtuel (.venv)..." -ForegroundColor Yellow
if (-not (Test-Path $venvPython)) {
    Write-Host "Création de l'environnement virtuel..." -ForegroundColor Gray
    Invoke-CheckedCommand -Executable $pythonExe -Arguments @("-m", "venv", $venvDir) -Operation "Création de l'environnement virtuel"
    Write-Host "[OK] Environnement virtuel créé." -ForegroundColor Green
} else {
    Write-Host "[OK] Environnement virtuel existant détecté." -ForegroundColor Green
}

$venvVersion = [string](& $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ($LASTEXITCODE -ne 0 -or -not $venvVersion -or $venvVersion.Trim() -ne "3.12") {
    throw "L'environnement .venv n'utilise pas Python 3.12. Supprimez .venv puis relancez install.ps1."
}

# 3. Installation des dépendances
Write-Host "`n[3/5] Installation des dépendances (requirements.txt)..." -ForegroundColor Yellow
Invoke-CheckedCommand -Executable $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "--quiet") -Operation "Mise à jour de pip"
Invoke-CheckedCommand -Executable $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $projectRoot "requirements.txt"), "--quiet") -Operation "Installation des dépendances"
Write-Host "[OK] Dépendances installées avec succès." -ForegroundColor Green

# 4. Génération des clés de sécurité souveraines (DataShield AES-256)
Write-Host "`n[4/5] Initialisation de la sécurité DataShield..." -ForegroundColor Yellow
$setupScript = Join-Path $projectRoot "scripts\setup_production.py"
Invoke-CheckedCommand -Executable $venvPython -Arguments @($setupScript) -Operation "Initialisation de DataShield"

# 5. Enregistrement du service d'arrière-plan (Tâche planifiée)
Write-Host "`n[5/5] Configuration du service résident d'arrière-plan..." -ForegroundColor Yellow
$installServiceScript = Join-Path $projectRoot "scripts\installer_service_windows.ps1"
if (-not (Test-Path $installServiceScript)) {
    throw "Script d'installation du service introuvable : $installServiceScript"
}
Invoke-CheckedCommand -Executable "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $installServiceScript, "-DemarrerImmediatement") -Operation "Configuration du service résident"

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "   🎉 Félicitations ! GreatOS est installé et actif !    " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "• Interface Web locale : http://127.0.0.1:8000/web/" -ForegroundColor White
Write-Host "• Pour contrôler le service : python greatos_service.py [status|stop|start|restart]" -ForegroundColor Gray
Write-Host "• Pour lancer les tests : .\.venv\Scripts\python.exe -m pytest tests/ -q" -ForegroundColor Gray
