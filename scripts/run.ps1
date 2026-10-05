# scripts/run.ps1 — Hub de commandes GreatOS
param([string]$Command = "help")

$Root = Split-Path $PSScriptRoot -Parent
$Python = "$Root\.venv\Scripts\python.exe"

switch ($Command) {
    "test" { & $Python -m pytest tests\ --tb=short -q }
    "test-core" { & $Python -m pytest tests\test_greatos_modules.py tests\test_tools.py tests\test_planning_and_api.py --tb=short -q }
    "health" { & $Python scripts\healthcheck.py }
    "start" { & $Python -m uvicorn interface_morphique.server:app --host 0.0.0.0 --port 8000 }
    "status" { & $Python greatos.py status }
    "snapshot" { & $Python greatos.py snapshot }
    "lint" { & $Python -m py_compile greatos.py greatos_contracts.py greatos_capabilities.py }
    "help" {
        Write-Host "Commandes disponibles :"
        Write-Host "  .\scripts\run.ps1 test       — Lancer toute la suite de tests"
        Write-Host "  .\scripts\run.ps1 test-core  — Tests core uniquement (rapide)"
        Write-Host "  .\scripts\run.ps1 health     — Healthcheck système"
        Write-Host "  .\scripts\run.ps1 start      — Démarrer l'API FastAPI"
        Write-Host "  .\scripts\run.ps1 status     — Afficher l'état du kernel"
        Write-Host "  .\scripts\run.ps1 snapshot   — Créer un snapshot"
        Write-Host "  .\scripts\run.ps1 lint       — Vérifier la syntaxe des fichiers core"
    }
    default { Write-Host "Commande inconnue : $Command. Utilisez 'help'." }
}
