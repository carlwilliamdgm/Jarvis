# Configuration de la tâche planifiée de recherche de mise à jour toutes les 12h
$ErrorActionPreference = "Stop"

$taskName = "JarvisAutoUpdate"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$updateScript = Join-Path $projectRoot "bootstrap\update.ps1"

if (-not (Test-Path $updateScript)) {
    Write-Host "[ERREUR] Le script de mise à jour est introuvable : $updateScript" -ForegroundColor Red
    exit 1
}

$taskRun = "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$updateScript`""

Write-Host "Création de la tâche planifiée '$taskName'..." -ForegroundColor Cyan
& schtasks.exe /Create /TN $taskName /TR $taskRun /SC HOURLY /MO 12 /F

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Tâche '$taskName' configurée avec succès :" -ForegroundColor Green
    Write-Host "   - Fréquence : Toutes les 12 heures (/SC HOURLY /MO 12)" -ForegroundColor Cyan
    Write-Host "   - Script exécuté : $updateScript" -ForegroundColor Cyan
} else {
    Write-Host "[ERREUR] Échec de création via schtasks (code $LASTEXITCODE)" -ForegroundColor Red
}

