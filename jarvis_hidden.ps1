# Script wrapper pour lancer Jarvis en arrière-plan sans fenêtre visible
$logFile = "C:\Users\Carl\Jarvis\logs\uvicorn.log"
$errFile = "C:\Users\Carl\Jarvis\logs\uvicorn.err.log"
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Start-Process -FilePath "C:\Program Files\Python312\python.exe" `
    -ArgumentList "-m uvicorn api.server:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory "C:\Users\Carl\Jarvis" `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile