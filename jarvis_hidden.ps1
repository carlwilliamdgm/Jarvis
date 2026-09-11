# Script wrapper pour lancer Jarvis en arrière-plan sans fenêtre visible
$projectRoot = $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logFile = Join-Path $projectRoot "logs\uvicorn.log"
$errFile = Join-Path $projectRoot "logs\uvicorn.err.log"
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Start-Process -FilePath $pythonExe `
    -ArgumentList "-m uvicorn interface_morphique.server:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile
