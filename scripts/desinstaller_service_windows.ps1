# Script de désinstallation propre du service d'arrière-plan GreatOS

$taskName = "JarvisAgent"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe   = Join-Path $projectRoot ".venv\Scripts\python.exe"

Write-Host "Arrêt de GreatOS..." -ForegroundColor Yellow
if (Test-Path $pythonExe) {
    & $pythonExe (Join-Path $projectRoot "greatos_service.py") stop
}

try {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] Tâche planifiée '$taskName' désinstallée." -ForegroundColor Green
} catch {
    Write-Host "[INFO] Aucune tâche planifiée '$taskName' trouvée." -ForegroundColor Gray
}
