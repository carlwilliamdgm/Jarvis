param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubPAT,
    [string]$InstallDir = ""
)

# Bootstrap installation script for Jarvis
# Usage: powershell.exe -ExecutionPolicy Bypass -File bootstrap\install.ps1 -GitHubPAT <your_pat>
# Requires Administrator privileges

$ErrorActionPreference = "Stop"
$LogPath = Join-Path $PSScriptRoot "bootstrap_install.log"
$JarvisDir = if ([string]::IsNullOrWhiteSpace($InstallDir)) { Join-Path $env:USERPROFILE "Jarvis" } else { $InstallDir }
$serviceName = "JarvisService"
$taskName = "JarvisAutoUpdate"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $logLine -Encoding UTF8
    Write-Host $logLine
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

# Helper: run a git command against the Jarvis repo without ever putting the
# PAT in the remote URL or in .git/config. The PAT is only ever exposed to
# git via a short-lived GIT_ASKPASS script, cleaned up immediately after use.
function Invoke-GitWithPAT {
    param(
        [Parameter(Mandatory=$true)][string[]]$GitArgs,
        [Parameter(Mandatory=$true)][string]$Pat
    )
    $askPassPath = Join-Path $env:TEMP "jarvis_askpass_$PID.cmd"
    "@echo off`r`necho %JARVIS_GIT_PAT%" | Out-File -FilePath $askPassPath -Encoding ASCII -Force

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
    } elseif (Test-Command "python") {
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
$env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

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
        $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
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

# Step 6: Register Windows service
Write-Log "=== Step 6: Register Windows Service ==="
$serviceScript = Join-Path $JarvisDir "service\windows_service.py"

# $pythonPath is now always a resolved .exe path (see Step 1), so no
# separate args string is needed to work around a multi-token invocation.
$pythonExeForService = $pythonPath
$pythonArgsForService = ""
$userSitePackages = ""
try {
    $userSitePackages = (& $pythonPath -m site --user-site 2>&1).Trim()
} catch {
    Write-Log "Could not detect Python user site-packages: $_" "WARN"
}

[System.Environment]::SetEnvironmentVariable("JARVIS_INSTALL_DIR", $JarvisDir, "Machine")
[System.Environment]::SetEnvironmentVariable("JARVIS_PYTHON_EXE", $pythonExeForService, "Machine")
[System.Environment]::SetEnvironmentVariable("JARVIS_PYTHON_ARGS", $pythonArgsForService, "Machine")
if (-not [string]::IsNullOrWhiteSpace($userSitePackages)) {
    [System.Environment]::SetEnvironmentVariable("JARVIS_USER_SITE_PACKAGES", $userSitePackages, "Machine")
}
$env:JARVIS_INSTALL_DIR = $JarvisDir
$env:JARVIS_PYTHON_EXE = $pythonExeForService
$env:JARVIS_PYTHON_ARGS = $pythonArgsForService
if (-not [string]::IsNullOrWhiteSpace($userSitePackages)) {
    $env:JARVIS_USER_SITE_PACKAGES = $userSitePackages
}

if (Test-Path $serviceScript) {
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

    if ($service) {
        Write-Log "Service $serviceName already exists"
        if ($service.Status -eq "Running") {
            Write-Log "Service is running"
        } else {
            Write-Log "Starting service..."
            Start-Service -Name $serviceName
            Write-Log "Service started"
        }
    } else {
        Write-Log "Registering service $serviceName"
        try {
            Push-Location $JarvisDir
            & $pythonPath $serviceScript install
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Service registered successfully"

                & sc.exe config $serviceName start= auto
                Write-Log "Service configured for automatic startup"

                Write-Log "Starting service..."
                Start-Service -Name $serviceName
                Write-Log "Service started"
            } else {
                Write-Log "Service registration failed with exit code $LASTEXITCODE" "ERROR"
                throw "Failed to register service"
            }
            Pop-Location
        } catch {
            Write-Log "Failed to register service: $_" "ERROR"
            Pop-Location
            throw
        }
    }

    $service = Get-Service -Name $serviceName
    if ($service.Status -eq "Running") {
        Write-Log "Service $serviceName is running"
    } else {
        Write-Log "Service $serviceName is not running (status: $($service.Status))" "WARN"
    }
} else {
    Write-Log "Service script not found at $serviceScript" "ERROR"
    throw "Service script not found"
}

# Step 7: Store PAT for future updates
# No cmdkey / Credential Manager: the PAT lives only in the Machine-level
# GIT_PAT_JARVIS env var, read by update.ps1 via GIT_ASKPASS (never in
# .git/config, never in a remote URL, never in logs).
Write-Log "=== Step 7: Store PAT for Future Updates ==="
[System.Environment]::SetEnvironmentVariable("GIT_PAT_JARVIS", $GitHubPAT, "Machine")
$env:GIT_PAT_JARVIS = $GitHubPAT
Write-Log "PAT stored in environment variable GIT_PAT_JARVIS (Machine-level)"

# Step 8: Display summary
Write-Log "=== Installation Summary ==="
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "                    INSTALLATION SUMMARY" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$status = @{ "Python 3.12" = $pythonInstalled; "Jarvis Repository" = (Test-Path $JarvisDir); "Dependencies" = $true; "API Keys" = ($groqKeys.Count -gt 0); "Ollama" = $ollamaInstalled; $serviceName = ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue) -ne $null); "PAT Storage" = $true }

foreach ($item in $status.Keys) {
    $symbol = if ($status[$item]) { "✅" } else { "❌" }
    Write-Host "$symbol $item" -ForegroundColor $(if ($status[$item]) { "Green" } else { "Red" })
}

Write-Host ""
Write-Host "Service Port: 8000" -ForegroundColor Yellow
Write-Host "Jarvis Directory: $JarvisDir" -ForegroundColor Yellow

$tailscaleIP = "N/A"
if (Test-Command "tailscale") {
    try {
        $tailscaleIP = & tailscale ip -4 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Tailscale IP: $tailscaleIP" -ForegroundColor Yellow
        }
    } catch {
        # Ignore Tailscale errors
    }
}

Write-Host ""
Write-Host "Installation log: $LogPath" -ForegroundColor Gray
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Create update.ps1 script
Write-Log "=== Creating update.ps1 script ==="
$updateScript = @'
$JarvisDir = [System.Environment]::GetEnvironmentVariable("JARVIS_INSTALL_DIR", "Machine")
if (-not $JarvisDir) {
    $JarvisDir = Join-Path $env:USERPROFILE "Jarvis"
}
$ServiceName = "JarvisService"
$LogPath = Join-Path $JarvisDir "bootstrap\update.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $logLine -Encoding UTF8
}

try {
    Write-Log "=== Starting Jarvis Auto-Update ==="

    # PAT read from the Machine-level env var only — never from Credential
    # Manager/cmdkey, never embedded in a remote URL or .git/config.
    $pat = [System.Environment]::GetEnvironmentVariable("GIT_PAT_JARVIS", "Machine")

    if (-not $pat) {
        Write-Log "PAT not found in GIT_PAT_JARVIS environment variable" "ERROR"
        exit 1
    }

    Push-Location $JarvisDir

    $currentHash = git rev-parse HEAD 2>&1
    Write-Log "Current commit: $currentHash"

    # Transient GIT_ASKPASS: the PAT is exposed to git only for the
    # duration of this pull, via an env var read by a throwaway script.
    $askPassPath = Join-Path $env:TEMP "jarvis_update_askpass_$PID.cmd"
    "@echo off`r`necho %JARVIS_UPDATE_PAT%" | Out-File -FilePath $askPassPath -Encoding ASCII -Force
    $env:GIT_ASKPASS = $askPassPath
    $env:JARVIS_UPDATE_PAT = $pat
    $env:GIT_TERMINAL_PROMPT = "0"

    git pull origin main
    $pullExit = $LASTEXITCODE

    Remove-Item $askPassPath -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\JARVIS_UPDATE_PAT -ErrorAction SilentlyContinue

    if ($pullExit -eq 0) {
        $newHash = git rev-parse HEAD 2>&1
        Write-Log "New commit: $newHash"

        if ($currentHash -eq $newHash) {
            Write-Log "OK — no changes detected"
        } else {
            Write-Log "Changes detected — restarting $ServiceName"

            Stop-Service -Name $ServiceName -Force
            Start-Sleep -Seconds 5
            Start-Service -Name $ServiceName

            Write-Log "Update applied — commit $currentHash → $newHash, service restarted"
        }
    } else {
        Write-Log "Git pull failed — service unchanged, reason: git error" "ERROR"
    }

    Pop-Location
} catch {
    Write-Log "Update failed: $_" "ERROR"
    exit 1
}
'@

$updateScriptPath = Join-Path $JarvisDir "bootstrap\update.ps1"
$updateScript | Out-File -FilePath $updateScriptPath -Encoding UTF8
Write-Log "update.ps1 created at $updateScriptPath"

# Register scheduled task for auto-update
Write-Log "=== Registering Scheduled Task ==="
$taskExists = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if (-not $taskExists) {
    try {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$updateScriptPath`""
        $trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 2 -At 4am
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Jarvis auto-update task (every 2 days)"
        Write-Log "Scheduled task '$taskName' registered successfully"
    } catch {
        Write-Log "Failed to register scheduled task: $_" "WARN"
    }
} else {
    Write-Log "Scheduled task '$taskName' already exists"
}

Write-Log "=== Installation Complete ==="