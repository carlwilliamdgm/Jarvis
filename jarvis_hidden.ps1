# Script wrapper pour lancer GreatOS en arrière-plan sans fenêtre visible
# Lancé via la tâche planifiée JarvisAgent (logon + quotidien 09h30)

$projectRoot = $PSScriptRoot
$pythonExe   = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logFile     = Join-Path $projectRoot "logs\uvicorn.log"
$errFile     = Join-Path $projectRoot "logs\uvicorn.err.log"
$logDir      = Split-Path $logFile -Parent

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Rotation automatique des logs si taille supérieure à 10 Mo
$maxLogBytes = 10 * 1024 * 1024
foreach ($file in @($logFile, $errFile)) {
    if ((Test-Path $file) -and ((Get-Item $file).Length -gt $maxLogBytes)) {
        $oldFile = "$file.old"
        if (Test-Path $oldFile) { Remove-Item $oldFile -Force -ErrorAction SilentlyContinue }
        Rename-Item -Path $file -NewName (Split-Path $oldFile -Leaf) -Force -ErrorAction SilentlyContinue
    }
}

# Vérifier si GreatOS tourne déjà sur le port 8000 (évite les doublons)
$portOccupe = $false
try {
    $conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($conn) { $portOccupe = $true }
} catch {}

if ($portOccupe) {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] GreatOS deja actif sur le port 8000 — demarrage ignore."
    exit 0
}

# Charger les variables d'environnement depuis .env si présent
$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
        }
    }
}

# Lancer uvicorn en héritant de l'environnement courant (inclut les vars .env)
$arguments = @("-m", "uvicorn", "interface_morphique.server:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "info")

$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile `
    -PassThru
