param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubPAT,
    [string]$InstallDir = ""
)

# Bootstrap installation script for Jarvis
# Usage: powershell.exe -ExecutionPolicy Bypass -File bootstrap\install.ps1 -GitHubPAT <your_pat>
# Requires Administrator privileges

$ErrorActionPreference = "Stop"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Ce script doit etre execute en tant qu'Administrateur." -ForegroundColor Red
    Write-Host "Relancez PowerShell en mode Administrateur, puis reessayez." -ForegroundColor Red
    throw "Privileges administrateur requis"
}

$LogPath = Join-Path $PSScriptRoot "bootstrap_install.log"
$JarvisDir = if ([string]::IsNullOrWhiteSpace($InstallDir)) { Join-Path $env:USERPROFILE "Jarvis" } else { $InstallDir }
$serviceName = "JarvisService"
$agentTaskName = "JarvisAgent"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $logLine -Encoding UTF8
    Write-Host $logLine
}

function Set-MachineEnvironmentVariableChecked {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [AllowEmptyString()][string]$Value
    )

    [System.Environment]::SetEnvironmentVariable($Name, $Value, "Machine")
    $confirmed = [System.Environment]::GetEnvironmentVariable($Name, "Machine")
    if ($confirmed -ne $Value) {
        Write-Log "Failed to persist Machine-level environment variable $Name. Expected '$Value', read back '$confirmed'." "ERROR"
        throw "Machine-level environment variable verification failed for $Name"
    }

    Write-Log "Confirmed Machine-level environment variable $Name"
}

function Test-Command {
    param([string]$Command)
    try {
        $null = Get-Command $Command -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Update-ProcessPathFromRegistry {
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $pathParts = @()
    if (-not [string]::IsNullOrWhiteSpace($machinePath)) { $pathParts += $machinePath }
    if (-not [string]::IsNullOrWhiteSpace($userPath)) { $pathParts += $userPath }
    $env:PATH = ($pathParts -join ";")
}

function Install-GitIfMissing {
    if (Test-Command "git") {
        Write-Log "Git already installed"
        return
    }

    Write-Log "Git not found. Downloading and installing Git for Windows..."
    $gitInstallerUrl = "https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe"
    $gitInstallerPath = Join-Path $env:TEMP "Git-64-bit.exe"

    try {
        Invoke-WebRequest -Uri $gitInstallerUrl -OutFile $gitInstallerPath -UseBasicParsing
        $gitArgs = "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS"
        $process = Start-Process -FilePath $gitInstallerPath -ArgumentList $gitArgs -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Git installer exited with code $($process.ExitCode)"
        }

        Update-ProcessPathFromRegistry
        if (-not (Test-Command "git")) {
            throw "Git installation completed but git.exe is still not available in PATH"
        }

        Write-Log "Git installed successfully"
    } catch {
        Write-Log "Failed to install Git: $_" "ERROR"
        throw
    } finally {
        Remove-Item $gitInstallerPath -Force -ErrorAction SilentlyContinue
    }
}

# Helper: run a git command against the Jarvis repo without ever putting the
# PAT in the remote URL or in .git/config. The PAT is only ever exposed to
# git via a short-lived GIT_ASKPASS script, cleaned up immediately after use.
function Invoke-GitWithPAT {
    param(
        [Parameter(Mandatory=$true)][string[]]$GitArgs,
        [Parameter(Mandatory=$true)][string]$Pat
    )
    $askPassPath = Join-Path $env:TEMP "jarvis_askpass_$PID.cmd"
    "@echo off`r`necho %1 | findstr /I `"Username`" >nul`r`nif %ERRORLEVEL%==0 (`r`n  echo x-access-token`r`n) else (`r`n  echo %JARVIS_GIT_PAT%`r`n)" | Out-File -FilePath $askPassPath -Encoding ASCII -Force

    $prevAskPass = $env:GIT_ASKPASS
    $prevTerminalPrompt = $env:GIT_TERMINAL_PROMPT
    $env:GIT_ASKPASS = $askPassPath
    $env:JARVIS_GIT_PAT = $Pat
    $env:GIT_TERMINAL_PROMPT = "0"

    try {
        & git @GitArgs
        return $LASTEXITCODE
    } finally {
        Remove-Item $askPassPath -Force -ErrorAction SilentlyContinue
        Remove-Item Env:\JARVIS_GIT_PAT -ErrorAction SilentlyContinue
        if ($null -ne $prevAskPass) { $env:GIT_ASKPASS = $prevAskPass } else { Remove-Item Env:\GIT_ASKPASS -ErrorAction SilentlyContinue }
        if ($null -ne $prevTerminalPrompt) { $env:GIT_TERMINAL_PROMPT = $prevTerminalPrompt } else { Remove-Item Env:\GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue }
    }
}

# Step 1: Detect/install Python 3.12
Write-Log "=== Step 1: Python 3.12 Detection/Installation ==="
$pythonInstalled = $false
$pythonPath = $null

# Check for python in standard locations
$standardPaths = @(
    "C:\Program Files\Python312\python.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
)

foreach ($path in $standardPaths) {
    if (Test-Path $path) {
        $pythonPath = $path
        $pythonInstalled = $true
        Write-Log "Python 3.12 found at: $path"
        break
    }
}

# Check via py launcher or python command — always resolve to a real .exe
# path (never a multi-token string like "py -3.12"), so every later
# invocation via `& $pythonPath ...` works without quoting tricks.
if (-not $pythonInstalled) {
    if (Test-Command "py") {
        $version = & py -3.12 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $resolved = (& py -3.12 -c "import sys; print(sys.executable)" 2>&1)
            if ($LASTEXITCODE -eq 0 -and (Test-Path ($resolved.Trim()))) {
                $pythonPath = $resolved.Trim()
                $pythonInstalled = $true
                Write-Log "Python 3.12 found via py launcher, resolved to: $pythonPath"
            }
        }
    }
    if (-not $pythonInstalled -and (Test-Command "python")) {
        $version = & python --version 2>&1
        if ($version -match "3\.12") {
            $pythonPath = (Get-Command python).Source
            $pythonInstalled = $true
            Write-Log "Python 3.12 found via python command, resolved to: $pythonPath"
        }
    }
}

if (-not $pythonInstalled) {
    Write-Log "Python 3.12 not found. Downloading installer..."
    try {
        $installerUrl = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        $installerPath = Join-Path $env:TEMP "python-3.12.7-amd64.exe"

        Write-Log "Downloading Python installer from $installerUrl"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

        Write-Log "Installing Python 3.12 silently..."
        $process = Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait -PassThru
        if ($process.ExitCode -eq 0) {
            Write-Log "Python 3.12 installed successfully"
            $pythonPath = "C:\Program Files\Python312\python.exe"
            $pythonInstalled = $true
        } else {
            throw "Python installer exited with code $($process.ExitCode)"
        }

        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Log "Failed to install Python 3.12: $_" "ERROR"
        throw
    }
}

# Refresh environment variables
Update-ProcessPathFromRegistry

# Step 1b: Detect/install Git
Write-Log "=== Step 1b: Git Detection/Installation ==="
Install-GitIfMissing

# Step 2: Clone the repo Jarvis
# The PAT is never embedded in the remote URL and never written to
# .git/config — it only ever exists transiently via GIT_ASKPASS (see
# Invoke-GitWithPAT above), for the duration of clone/pull.
Write-Log "=== Step 2: Clone Jarvis Repository ==="
$repoUrl = "https://github.com/carlwilliamdgm/Jarvis.git"

if (Test-Path $JarvisDir) {
    $gitDir = Join-Path $JarvisDir ".git"
    if (Test-Path $gitDir) {
        Write-Log "Repository already exists. Performing git pull..."
        try {
            Push-Location $JarvisDir
            $currentHash = & git rev-parse HEAD 2>&1
            Write-Log "Current commit: $currentHash"

            $pullExit = Invoke-GitWithPAT -GitArgs @("pull", "origin", "main") -Pat $GitHubPAT
            if ($pullExit -eq 0) {
                $newHash = & git rev-parse HEAD 2>&1
                Write-Log "Git pull successful. New commit: $newHash"
            } else {
                Write-Log "Git pull failed. Continuing with existing version." "WARN"
            }
            Pop-Location
        } catch {
            Write-Log "Git pull failed: $_" "WARN"
            Pop-Location
        }
    } else {
        Write-Log "Directory exists but is not a git repo. Removing and cloning..."
        Remove-Item $JarvisDir -Recurse -Force
        $cloneExit = Invoke-GitWithPAT -GitArgs @("clone", $repoUrl, $JarvisDir) -Pat $GitHubPAT
        if ($cloneExit -ne 0) {
            Write-Log "Git clone failed" "ERROR"
            throw "Failed to clone repository"
        }
        Write-Log "Repository cloned successfully"
    }
} else {
    Write-Log "Cloning repository to $JarvisDir"
    $cloneExit = Invoke-GitWithPAT -GitArgs @("clone", $repoUrl, $JarvisDir) -Pat $GitHubPAT
    if ($cloneExit -ne 0) {
        Write-Log "Git clone failed" "ERROR"
        throw "Failed to clone repository"
    }
    Write-Log "Repository cloned successfully"
}

# Step 3: Install Python dependencies
Write-Log "=== Step 3: Install Python Dependencies ==="
$requirementsPath = Join-Path $JarvisDir "requirements.txt"
if (Test-Path $requirementsPath) {
    try {
        Push-Location $JarvisDir
        & $pythonPath -m pip install -r requirements.txt
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Dependencies installed successfully"
        } else {
            Write-Log "pip install failed with exit code $LASTEXITCODE" "ERROR"
            throw "Failed to install dependencies"
        }
        Pop-Location
    } catch {
        Write-Log "Failed to install dependencies: $_" "ERROR"
        Pop-Location
        throw
    }
} else {
    Write-Log "requirements.txt not found at $requirementsPath" "ERROR"
    throw "requirements.txt not found"
}

# Step 3b: Playwright browser binaries (for autonomous web navigation)
Write-Log "=== Step 3b: Playwright Chromium Browser ==="
$playwrightInstalled = $false
$localAppData = [System.Environment]::GetFolderPath("LocalApplicationData")
$pwDir = Join-Path $localAppData "ms-playwright"
if ((Test-Path $pwDir) -and ((Get-ChildItem -Path $pwDir -Filter "chromium*" -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)) {
    Write-Log "Navigateur Chromium Playwright déjà présent — étape ignorée"
    $playwrightInstalled = $true
} else {
    Write-Log "Installation de Chromium pour Playwright..."
    try {
        & $pythonPath -m playwright install chromium
        if ($LASTEXITCODE -eq 0) {
            $playwrightInstalled = $true
            Write-Log "Chromium Playwright installé avec succès"
        } else {
            Write-Log "Échec de l'installation de Playwright Chromium (code: $LASTEXITCODE)" "WARN"
        }
    } catch {
        Write-Log "Erreur lors de l'installation Playwright: $_" "WARN"
    }
}

# Step 3c: Local Voice Models (Vosk STT, Piper TTS, openWakeWord)
Write-Log "=== Step 3c: Local Voice Models ==="
$modelsDir = Join-Path $JarvisDir "models"
if (-not (Test-Path $modelsDir)) {
    New-Item -ItemType Directory -Path $modelsDir -Force | Out-Null
}

# Vosk French model (~40 MB)
$voskFrDir = Join-Path $modelsDir "vosk-model-small-fr-0.22"
if (Test-Path $voskFrDir) {
    Write-Log "Modèle Vosk FR déjà présent dans $voskFrDir"
} else {
    Write-Log "Téléchargement du modèle de reconnaissance vocale Vosk FR (~40 Mo)..."
    try {
        $voskZipUrl = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
        $voskZipPath = Join-Path $env:TEMP "vosk-model-small-fr-0.22.zip"
        Invoke-WebRequest -Uri $voskZipUrl -OutFile $voskZipPath -UseBasicParsing
        Expand-Archive -Path $voskZipPath -DestinationPath $modelsDir -Force
        Remove-Item $voskZipPath -Force -ErrorAction SilentlyContinue
        Write-Log "Modèle Vosk FR extrait avec succès"
    } catch {
        Write-Log "Impossible de télécharger Vosk FR: $_" "WARN"
    }
}

# Piper TTS French model (~28 MB)
$piperDir = Join-Path $modelsDir "piper"
$piperModel = Join-Path $piperDir "fr_FR-siwis-low.onnx"
$piperConfig = Join-Path $piperDir "fr_FR-siwis-low.onnx.json"
if (-not (Test-Path $piperDir)) {
    New-Item -ItemType Directory -Path $piperDir -Force | Out-Null
}
if ((Test-Path $piperModel) -and (Test-Path $piperConfig)) {
    Write-Log "Modèle Piper TTS FR déjà présent dans $piperDir"
} else {
    Write-Log "Téléchargement du modèle de synthèse vocale Piper TTS (~28 Mo)..."
    try {
        $piperBaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/low"
        Invoke-WebRequest -Uri "$piperBaseUrl/fr_FR-siwis-low.onnx" -OutFile $piperModel -UseBasicParsing
        Invoke-WebRequest -Uri "$piperBaseUrl/fr_FR-siwis-low.onnx.json" -OutFile $piperConfig -UseBasicParsing
        Write-Log "Modèle Piper TTS FR téléchargé avec succès"
    } catch {
        Write-Log "Impossible de télécharger Piper TTS: $_" "WARN"
    }
}

# openWakeWord model (hey_jarvis)
Write-Log "Vérification du modèle de réveil openWakeWord (hey_jarvis)..."
try {
    & $pythonPath -c "import openwakeword.utils; openwakeword.utils.download_models(['hey_jarvis'])"
    Write-Log "Modèle openWakeWord vérifié"
} catch {
    Write-Log "openWakeWord verification: $_" "WARN"
}

# Step 3d: DataShield AES-256 Crypto Key Generation
Write-Log "=== Step 3d: DataShield AES-256 Key ==="
$existingCrypto = [System.Environment]::GetEnvironmentVariable("JARVIS_CRYPTO_KEY", "Machine")
if (-not [string]::IsNullOrWhiteSpace($existingCrypto)) {
    Write-Log "Clé DataShield/crypto déjà présente au niveau Machine"
} else {
    try {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $cryptoKey = [Convert]::ToBase64String($bytes)
        Set-MachineEnvironmentVariableChecked -Name "JARVIS_CRYPTO_KEY" -Value $cryptoKey
        $env:JARVIS_CRYPTO_KEY = $cryptoKey
        Write-Log "Clé cryptographique DataShield (AES-256-GCM) générée et enregistrée avec succès"
    } catch {
        Write-Log "Impossible de générer JARVIS_CRYPTO_KEY: $_" "WARN"
    }
}

# Step 4: Configure API keys (skips prompts if keys already exist Machine-level)
Write-Log "=== Step 4: Configure API Keys ==="

$existingGroqKeys = @()
for ($i = 1; $i -le 5; $i++) {
    $existing = [System.Environment]::GetEnvironmentVariable("GROQ_API_KEY_$i", "Machine")
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        $existingGroqKeys += $existing
    }
}

$groqKeys = @()

if ($existingGroqKeys.Count -gt 0) {
    Write-Log "$($existingGroqKeys.Count) clé(s) Groq déjà présente(s) — saisie ignorée"
    $groqKeys = $existingGroqKeys
} else {
    $keyIndex = 1
    Write-Host ""
    Write-Host "Configuration des clés API Groq (1 à 5 clés, minimum 1 requise)" -ForegroundColor Cyan
    Write-Host "Appuyez sur Entrée sans saisir de clé pour terminer" -ForegroundColor Cyan

    while ($keyIndex -le 5) {
        $key = Read-Host "Clé Groq #$keyIndex (ou Entrée pour terminer)"
        if ([string]::IsNullOrWhiteSpace($key)) {
            if ($groqKeys.Count -eq 0) {
                Write-Host "Au moins une clé Groq est requise" -ForegroundColor Red
                continue
            }
            break
        }
        $groqKeys += $key.Trim()
        $keyIndex++
    }

    for ($i = 0; $i -lt $groqKeys.Count; $i++) {
        $varName = "GROQ_API_KEY_$($i + 1)"
        [System.Environment]::SetEnvironmentVariable($varName, $groqKeys[$i], "Machine")
        Write-Log "Groq key #$($i + 1) stored in environment variable $varName"
    }
}

# OpenRouter key (optional)
$existingOpenRouter = [System.Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "Machine")
if (-not [string]::IsNullOrWhiteSpace($existingOpenRouter)) {
    Write-Log "Clé OpenRouter déjà présente — saisie ignorée"
} else {
    Write-Host ""
    Write-Host "Clé API OpenRouter (optionnel, appuyez sur Entrée pour passer)" -ForegroundColor Cyan
    $openRouterKey = Read-Host "Clé OpenRouter"
    if (-not [string]::IsNullOrWhiteSpace($openRouterKey)) {
        [System.Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", $openRouterKey.Trim(), "Machine")
        Write-Log "OpenRouter key stored in environment variable OPENROUTER_API_KEY"
    }
}

# Step 5: Detect/install Ollama
Write-Log "=== Step 5: Ollama Detection/Installation ==="
$ollamaInstalled = Test-Command "ollama"

if (-not $ollamaInstalled) {
    Write-Log "Ollama not found. Downloading and installing..."
    try {
        $ollamaUrl = "https://ollama.com/download/OllamaSetup.exe"
        $ollamaInstaller = Join-Path $env:TEMP "OllamaSetup.exe"

        Write-Log "Downloading Ollama installer from $ollamaUrl"
        Invoke-WebRequest -Uri $ollamaUrl -OutFile $ollamaInstaller -UseBasicParsing

        Write-Log "Installing Ollama silently..."
        $process = Start-Process -FilePath $ollamaInstaller -ArgumentList "/silent" -Wait -PassThru
        if ($process.ExitCode -eq 0) {
            Write-Log "Ollama installed successfully"
            $ollamaInstalled = $true
        } else {
            Write-Log "Ollama installer exited with code $($process.ExitCode)" "WARN"
        }

        Remove-Item $ollamaInstaller -Force -ErrorAction SilentlyContinue

        # Refresh PATH
        Update-ProcessPathFromRegistry
        $ollamaInstalled = Test-Command "ollama"
    } catch {
        Write-Log "Failed to install Ollama: $_" "ERROR"
        throw
    }
} else {
    Write-Log "Ollama already installed"
}

# Pull qwen2.5:7b model (skip if already present)
if ($ollamaInstalled) {
    $modelPresent = $false
    try {
        $existingModels = & ollama list 2>&1
        if ($existingModels -match "qwen2\.5:7b") {
            $modelPresent = $true
            Write-Log "Ollama model qwen2.5:7b already present — skipping pull"
        }
    } catch {
        Write-Log "Could not check existing Ollama models: $_" "WARN"
    }

    if (-not $modelPresent) {
        Write-Log "Pulling Ollama model qwen2.5:7b (this may take several minutes)..."
        try {
            $process = Start-Process -FilePath "ollama" -ArgumentList "pull", "qwen2.5:7b" -Wait -PassThru -NoNewWindow
            if ($process.ExitCode -eq 0) {
                Write-Log "Ollama model qwen2.5:7b pulled successfully"
            } else {
                Write-Log "Ollama pull failed with exit code $($process.ExitCode)" "WARN"
            }
        } catch {
            Write-Log "Failed to pull Ollama model: $_" "WARN"
        }
    }
}

# Step 6: Register the interactive scheduled task
Write-Log "=== Step 6: Register JarvisAgent Scheduled Task ==="

# The update script also needs the installation directory when a custom
# destination was selected.
Set-MachineEnvironmentVariableChecked -Name "JARVIS_INSTALL_DIR" -Value $JarvisDir
$env:JARVIS_INSTALL_DIR = $JarvisDir

# Jarvis must run in the interactive user's session: CLI, Web and Tkinter then
# share the same permissions, profile and hardware access. The legacy service
# runs as LocalSystem and is intentionally disabled when present.
$legacyService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($legacyService) {
    if ($legacyService.Status -eq "Running") {
        Stop-Service -Name $serviceName -Force
        Write-Log "Stopped legacy service $serviceName"
    }
    Set-Service -Name $serviceName -StartupType Disabled
    Write-Log "Disabled legacy service $serviceName"
}

$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskAction = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "-m uvicorn interface_morphique.server:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $JarvisDir
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $agentTaskName `
    -Action $taskAction `
    -Trigger $taskTrigger `
    -Principal $taskPrincipal `
    -Settings $taskSettings `
    -Description "Lance l'API Jarvis dans la session Windows de l'utilisateur." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $agentTaskName
Write-Log "Scheduled task $agentTaskName registered and started for $taskUser"

# Step 7: Store PAT for future updates
# No cmdkey / Credential Manager: the PAT lives only in the Machine-level
# GIT_PAT_JARVIS env var, read by update.ps1 via GIT_ASKPASS (never in
# .git/config, never in a remote URL, never in logs).
Write-Log "=== Step 7: Store PAT for Future Updates ==="
[System.Environment]::SetEnvironmentVariable("GIT_PAT_JARVIS", $GitHubPAT, "Machine")
$env:GIT_PAT_JARVIS = $GitHubPAT
Write-Log "PAT stored in environment variable GIT_PAT_JARVIS (Machine-level)"

# Step 7b: Create Desktop Shortcut
Write-Log "=== Step 7b: Create Desktop Shortcut ==="
try {
    $desktopPath = [System.Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "GreatOS Jarvis.url"
    "[InternetShortcut]`r`nURL=http://localhost:8000`r`nIconIndex=0" | Out-File -FilePath $shortcutPath -Encoding ASCII -Force
    Write-Log "Raccourci 'GreatOS Jarvis' créé sur le Bureau de l'utilisateur"
} catch {
    Write-Log "Impossible de créer le raccourci Bureau: $_" "WARN"
}

# Step 8: Display summary
Write-Log "=== Installation Summary ==="

$agentTaskRegistered = ((Get-ScheduledTask -TaskName $agentTaskName -ErrorAction SilentlyContinue) -ne $null)

$status = [ordered]@{
    "Python 3.12"       = $pythonInstalled
    "Chromium (Playwright)" = $playwrightInstalled
    "Modèles Vocaux Offline" = (Test-Path (Join-Path $JarvisDir "models\piper\fr_FR-siwis-low.onnx"))
    "Clé DataShield (AES-256)" = (-not [string]::IsNullOrWhiteSpace([System.Environment]::GetEnvironmentVariable("JARVIS_CRYPTO_KEY", "Machine")))
    "Raccourci Bureau"  = (Test-Path (Join-Path ([System.Environment]::GetFolderPath("Desktop")) "GreatOS Jarvis.url"))
    "Jarvis Repository" = (Test-Path $JarvisDir)
    "Dependencies"      = $true
    "API Keys"          = ($groqKeys.Count -gt 0)
    "Ollama"            = $ollamaInstalled
    "Tâche JarvisAgent" = $agentTaskRegistered
    "PAT Storage"       = $true
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════"
Write-Host "                    INSTALLATION SUMMARY"
Write-Host "═══════════════════════════════════════════════════════════"
foreach ($key in $status.Keys) {
    $mark = if ($status[$key]) { "[OK]" } else { "[--]" }
    Write-Host ("  {0,-4} {1}" -f $mark, $key)
}
Write-Host "═══════════════════════════════════════════════════════════"

