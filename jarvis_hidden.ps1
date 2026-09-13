# Script wrapper pour lancer Jarvis en arrière-plan sans fenêtre visible
$projectRoot = $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logFile = Join-Path $projectRoot "logs\uvicorn.log"
$errFile = Join-Path $projectRoot "logs\uvicorn.err.log"
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Rotation automatique des logs si taille superieure a 10 Mo
$maxLogBytes = 10 * 1024 * 1024
foreach ($file in @($logFile, $errFile)) {
    if ((Test-Path $file) -and ((Get-Item $file).Length -gt $maxLogBytes)) {
        $oldFile = "$file.old"
        if (Test-Path $oldFile) { Remove-Item $oldFile -Force -ErrorAction SilentlyContinue }
        Rename-Item -Path $file -NewName (Split-Path $oldFile -Leaf) -Force -ErrorAction SilentlyContinue
    }
}

Start-Process -FilePath $pythonExe `
    -ArgumentList "-m interface_morphique.server" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile
