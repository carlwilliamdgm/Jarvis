# Script wrapper pour lancer GreatOS en arrière-plan sans fenêtre visible
# Lancé via la tâche planifiée JarvisAgent (logon + quotidien 09h30)

param(
    [string]$PythonExe,
    [string]$HostAddress = "127.0.0.1"
)

$projectRoot = $PSScriptRoot
$pythonExe = if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    Join-Path $projectRoot ".venv\Scripts\python.exe"
} else {
    $PythonExe
}
$logFile     = Join-Path $projectRoot "logs\uvicorn.log"
$errFile     = Join-Path $projectRoot "logs\uvicorn.err.log"
$launcherLog = Join-Path $projectRoot "logs\launcher.log"
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

function Test-GreatOSReady {
    $scheme = if ($env:GREATOS_TLS_CERT_FILE -and $env:GREATOS_TLS_KEY_FILE) { "https" } else { "http" }
    try {
        $response = Invoke-WebRequest `
            -Uri "$($scheme)://127.0.0.1:8000/jarvis/status" `
            -UseBasicParsing `
            -TimeoutSec 3 `
            -ErrorAction Stop
        if ($response.StatusCode -ne 200) { return $false }
        $data = $response.Content | ConvertFrom-Json
        return ($null -ne $data) -and ($data.active -eq $true)
    } catch {
        return $false
    }
}

if (-not (Test-Path $pythonExe -PathType Leaf)) {
    throw "Interpréteur Python introuvable : $pythonExe"
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

if (Test-GreatOSReady) {
    try { Add-Content -Path $launcherLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] GreatOS déjà prêt sur le port 8000 — démarrage ignoré." } catch {}
    exit 0
}

# La tâche JarvisAgent lance l'expérience vocale continue demandée. Ce mode
# explicite prévaut sur GREATOS_DISABLE_VOICE éventuellement défini dans .env.
$env:GREATOS_DISABLE_VOICE = "0"
$env:JARVIS_API_HOST = $HostAddress
$env:JARVIS_API_PORT = "8000"

# Lancer uvicorn en héritant de l'environnement courant (inclut les vars .env)
$arguments = @("-m", "interface_morphique.server", "--host", $HostAddress, "--port", "8000")

$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile `
    -PassThru

$startupClock = [System.Diagnostics.Stopwatch]::StartNew()
while ($startupClock.Elapsed -lt [TimeSpan]::FromSeconds(90)) {
    if (Test-GreatOSReady) {
        try { Add-Content -Path $launcherLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] GreatOS prêt (PID $($proc.Id))." } catch {}
        exit 0
    }

    $proc.Refresh()
    if ($proc.HasExited) {
        throw "Le serveur GreatOS s'est arrêté pendant le démarrage (code $($proc.ExitCode)). Consultez $errFile."
    }
    Start-Sleep -Milliseconds 500
}

throw "Le serveur GreatOS courant n'a pas répondu sur http://127.0.0.1:8000/openapi.json après 90 secondes. Consultez $logFile et $errFile."
