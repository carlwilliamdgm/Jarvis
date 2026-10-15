# Script d'installation portable de GreatOS en tâche de fond Windows
# Fonctionne sur n'importe quel ordinateur, quel que soit le compte et l'emplacement du dossier.

param(
    [switch]$DemarrerImmediatement = $true
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe   = Join-Path $projectRoot ".venv\Scripts\python.exe"
$hiddenScript = Join-Path $projectRoot "jarvis_hidden.ps1"
$taskName    = "JarvisAgent"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Test-GreatOSReady {
    $apiScheme = "http"
    $tlsCert = $null
    $tlsKey = $null
    $envFile = Join-Path $projectRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*GREATOS_TLS_CERT_FILE\s*=\s*(.+)$') { $tlsCert = $Matches[1].Trim().Trim('"') }
            if ($line -match '^\s*GREATOS_TLS_KEY_FILE\s*=\s*(.+)$') { $tlsKey = $Matches[1].Trim().Trim('"') }
        }
    }
    if ($tlsCert -and $tlsKey) { $apiScheme = "https" }
    try {
        $response = Invoke-WebRequest `
            -Uri "$($apiScheme)://localhost:8000/openapi.json" `
            -UseBasicParsing `
            -TimeoutSec 1 `
            -ErrorAction Stop
        if ($response.StatusCode -ne 200) { return $false }
        $paths = ($response.Content | ConvertFrom-Json).paths
        return ($null -ne $paths) `
            -and ($null -ne $paths.PSObject.Properties['/jarvis/onboarding']) `
            -and ($null -ne $paths.PSObject.Properties['/jarvis/security/hello/enrollment/key-confirm']) `
            -and ($null -ne $paths.PSObject.Properties['/jarvis/security/unlock/hello/verify']) `
            -and ($null -ne $paths.PSObject.Properties['/jarvis/security/unlock/dpapi'])
    } catch {
        return $false
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Installation Portable du Service Résident GreatOS     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Dossier projet : $projectRoot" -ForegroundColor Gray
Write-Host "Utilisateur    : $currentUser" -ForegroundColor Gray

# 1. Vérifier la présence du venv
if (-not (Test-Path $pythonExe)) {
    Write-Host "[ERREUR] L'environnement virtuel n'a pas été trouvé dans .venv\Scripts\python.exe" -ForegroundColor Red
    Write-Host "Veuillez d'abord exécuter : python -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# 2. Vérifier/Générer les secrets de production (.env)
$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[INFO] Génération automatique des clés cryptographiques souveraines..." -ForegroundColor Yellow
    & $pythonExe (Join-Path $projectRoot "scripts\setup_production.py")
}

# 3. Préparer l'action de la tâche planifiée
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$hiddenScript`"" `
    -WorkingDirectory $projectRoot

# 4. Déclencheurs : à la connexion de session utilisateur (LogOn)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser

# 5. Paramètres de résilience
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)

# 6. Principal : compte courant
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest

# 7. Enregistrer la tâche planifiée
try {
    # Supprimer l'ancienne tâche si elle existait déjà
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Service d'arrière-plan intelligent GreatOS (Résident sur session utilisateur)." `
        | Out-Null

    Write-Host "[OK] Tâche planifiée '$taskName' créée avec succès pour $currentUser." -ForegroundColor Green
} catch {
    Write-Host "[AVERTISSEMENT] Droits Highest refusés, tentative avec droits standards..." -ForegroundColor Yellow
    $principalStd = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principalStd `
        -Description "Service d'arrière-plan intelligent GreatOS (Session utilisateur)." `
        | Out-Null
    Write-Host "[OK] Tâche planifiée '$taskName' créée avec succès (droits standards)." -ForegroundColor Green
}

# 7b. Enregistrer la tâche planifiée de mise à jour automatique (2 fois par jour / toutes les 12 heures)
$updateTaskName = "JarvisAutoUpdate"
$updateScript   = Join-Path $projectRoot "bootstrap\update.ps1"

if (Test-Path $updateScript) {
    try {
        Unregister-ScheduledTask -TaskName $updateTaskName -Confirm:$false -ErrorAction SilentlyContinue

        $updateAction = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$updateScript`"" `
            -WorkingDirectory $projectRoot

        # Déclencheur : Répétition toutes les 12 heures indéfiniment
        $updateTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 12)
        $updateTrigger.Repetition.Duration = ""

        $updateSettings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1)

        $updatePrincipal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive

        Register-ScheduledTask `
            -TaskName $updateTaskName `
            -Action $updateAction `
            -Trigger $updateTrigger `
            -Settings $updateSettings `
            -Principal $updatePrincipal `
            -Description "Recherche et application des mises à jour de GreatOS toutes les 12 heures." `
            | Out-Null

        Write-Host "[OK] Tâche de mise à jour automatique '$updateTaskName' configurée (toutes les 12 heures)." -ForegroundColor Green
    } catch {
        Write-Host "[AVERTISSEMENT] Impossible de créer la tâche '$updateTaskName' : $_" -ForegroundColor Yellow
    }
}

# 8. Démarrer immédiatement si demandé
if ($DemarrerImmediatement) {
    Write-Host "[INFO] Démarrage de GreatOS en arrière-plan..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $taskName
    $apiReady = $false
    $startupClock = [System.Diagnostics.Stopwatch]::StartNew()
    while ($startupClock.Elapsed -lt [TimeSpan]::FromSeconds(30)) {
        if (Test-GreatOSReady) {
            $apiReady = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $apiReady) {
        $startupLog = Join-Path $projectRoot "logs\uvicorn.err.log"
        throw "GreatOS API did not become ready within 30 seconds. Check $startupLog"
    }
    Write-Host "[OK] GreatOS API courant confirmé par son contrat OpenAPI." -ForegroundColor Green
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "GreatOS est opérationnel et démarrera automatiquement à chaque connexion !" -ForegroundColor Green
