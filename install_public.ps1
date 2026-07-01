# Jarvis Bootstrap Installation Script
# Public repo: carlwilliamdgm/Installation
# Usage: irm https://raw.githubusercontent.com/carlwilliamdgm/Installation/main/install.ps1 | iex
# Requires Administrator privileges

$ErrorActionPreference = "Stop"
$LogPath = "$env:USERPROFILE\bootstrap_install.log"
$JarvisDir = Join-Path $env:USERPROFILE "Jarvis"

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

function Refresh-Path {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# ÉTAPE 0 — Vérification droits administrateur
Write-Log "=== Step 0: Administrator Privilege Check ==="
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Please right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}
Write-Log "Administrator privileges confirmed"

# ÉTAPE 0.1 — Vérification connectivité réseau
Write-Log "=== Step 0.1: Network Connectivity Check ==="
try {
    $networkTest = Test-NetConnection -ComputerName github.com -Port 443 -WarningAction SilentlyContinue -ErrorAction Stop
    if ($networkTest.TcpTestSucceeded) {
        Write-Log "Network connectivity to GitHub confirmed"
    } else {
        Write-Log "Network connectivity to GitHub failed" "ERROR"
        Write-Host "ERROR: No network connection available. Cannot reach github.com:443" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Log "Network connectivity check failed: $_" "ERROR"
    Write-Host "ERROR: No network connection available. Cannot reach github.com:443" -ForegroundColor Red
    exit 1
}

# ÉTAPE 0.2 — Saisie interactive du PAT
Write-Log "=== Step 0.2: GitHub PAT Input ==="
$GitHubPAT = $null
while (-not $GitHubPAT) {
    $GitHubPAT = Read-Host "Entrez votre Personal Access Token GitHub (scope: repo sur carlwilliamdgm/Jarvis)"
    if ([string]::IsNullOrWhiteSpace($GitHubPAT)) {
        Write-Host "Le PAT ne peut pas être vide. Veuillez réessayer." -ForegroundColor Yellow
    }
}
Write-Log "GitHub PAT received (not logged for security)"

# ÉTAPE 0.3 — Détection/installation Git
Write-Log "=== Step 0.3: Git Detection/Installation ==="
$gitInstalled = Test-Command "git"

if (-not $gitInstalled) {
    Write-Log "Git not found. Downloading installer..."
    try {
        # Get latest Git for Windows release URL
        $releasesApi = "https://api.github.com/repos/git-for-windows/git/releases/latest"
        $releasesInfo = Invoke-RestMethod -Uri $releasesApi -ErrorAction Stop
        
        $gitInstallerUrl = $null
        foreach ($asset in $releasesInfo.assets) {
            if ($asset.name -match "Git-\d+\.\d+\.\d+.*-64-bit\.exe$") {
                $gitInstallerUrl = $asset.browser_download_url
                break
            }
        }
        
        if (-not $gitInstallerUrl) {
            throw "Could not find Git installer URL in latest release"
        }
        
        Write-Log "Downloading Git installer from $gitInstallerUrl"
        $gitInstallerPath = Join-Path $env:TEMP "Git-installer.exe"
        Invoke-WebRequest -Uri $gitInstallerUrl -OutFile $gitInstallerPath -UseBasicParsing
        
        Write-Log "Installing Git silently..."
        $process = Start-Process -FilePath $gitInstallerPath -ArgumentList "/VERYSILENT /NORESTART /COMPONENTS=`"icons,ext\reg\shellhere,assoc,assoc_sh`"" -Wait -PassThru
        if ($process.ExitCode -eq 0) {
            Write-Log "Git installed successfully"
            Refresh-Path
            $gitInstalled = Test-Command "git"
            if (-not $gitInstalled) {
                throw "Git installation completed but command not found"
            }
        } else {
            throw "Git installer exited with code $($process.ExitCode)"
        }
        
        Remove-Item $gitInstallerPath -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Log "Failed to install Git: $_" "ERROR"
        Write-Host "ERROR: Failed to install Git. Please install manually from https://git-scm.com/download/win" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Log "Git already installed"
}

# ÉTAPE 1 — Détection/installation Python 3.12
Write-Log "=== Step 1: Python 3.12 Detection/Installation ==="
$pythonInstalled = $false
$pythonCommand = $null
$pythonArgs = @()

# Check for python in standard locations
$standardPaths = @(
    "C:\Program Files\Python312\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe"
)

foreach ($path in $standardPaths) {
    if (Test-Path $path) {
        $pythonInstalled = $true
        $pythonCommand = $path
        $pythonArgs = @()
        Write-Log "Python 3.12 found at: $path"
        break
    }
}

# Check via py launcher
if (-not $pythonInstalled) {
    if (Test-Command "py") {
        try {
            $versionOutput = & py --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                # Check if 3.12 is available via py launcher
                $versionCheck = & py -3.12 --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $pythonInstalled = $true
                    $pythonCommand = "py"
                    $pythonArgs = @("-3.12")
                    Write-Log "Python 3.12 found via py launcher: $versionCheck"
                }
            }
        } catch {
            # py launcher not usable
        }
    }
}

# Check via python command
if (-not $pythonInstalled) {
    if (Test-Command "python") {
        try {
            $version = & python --version 2>&1
            if ($version -match "3\.12") {
                $pythonInstalled = $true
                $pythonCommand = "python"
                $pythonArgs = @()
                Write-Log "Python 3.12 found via python command: $version"
            }
        } catch {
            # python command not usable
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
            Refresh-Path
            $pythonInstalled = $true
            $pythonCommand = "C:\Program Files\Python312\python.exe"
            $pythonArgs = @()
        } else {
            throw "Python installer exited with code $($process.ExitCode)"
        }
        
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Log "Failed to install Python 3.12: $_" "ERROR"
        Write-Host "ERROR: Failed to install Python 3.12" -ForegroundColor Red
        exit 1
    }
}

# ÉTAPE 2 — Clone du repo Jarvis privé
Write-Log "=== Step 2: Clone Jarvis Repository ==="
$repoUrlWithPat = "https://${GitHubPAT}@github.com/carlwilliamdgm/Jarvis.git"
$repoUrlClean = "https://github.com/carlwilliamdgm/Jarvis.git"

if (Test-Path $JarvisDir) {
    # Check if it's a valid git repo
    $gitDir = Join-Path $JarvisDir ".git"
    if (Test-Path $gitDir) {
        Write-Log "Repository already exists. Performing git pull..."
        try {
            Push-Location $JarvisDir
            $currentHash = & git rev-parse HEAD 2>&1
            Write-Log "Current commit: $currentHash"
            
            # Use git config to pass PAT without storing in remote
            & git -c "http.extraHeader=Authorization: token $GitHubPAT" pull origin main
            if ($LASTEXITCODE -eq 0) {
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
        & git clone $repoUrlWithPat $JarvisDir
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Git clone failed" "ERROR"
            Write-Host "ERROR: Failed to clone repository. Check your PAT permissions." -ForegroundColor Red
            exit 1
        }
        Write-Log "Repository cloned successfully"
        
        # Immediately remove PAT from remote
        Push-Location $JarvisDir
        & git remote set-url origin $repoUrlClean
        Write-Log "Removed PAT from git remote"
        Pop-Location
    }
} else {
    Write-Log "Cloning repository to $JarvisDir"
    & git clone $repoUrlWithPat $JarvisDir
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Git clone failed" "ERROR"
        Write-Host "ERROR: Failed to clone repository. Check your PAT permissions." -ForegroundColor Red
        exit 1
    }
    Write-Log "Repository cloned successfully"
    
    # Immediately remove PAT from remote
    Push-Location $JarvisDir
    & git remote set-url origin $repoUrlClean
    Write-Log "Removed PAT from git remote"
    Pop-Location
}

# Verify remote doesn't contain PAT
Push-Location $JarvisDir
$remoteConfig = & git remote -v
Write-Log "Git remote configuration: $remoteConfig"
Pop-Location

# ÉTAPE 3 — Installation dépendances Python
Write-Log "=== Step 3: Install Python Dependencies ==="
$requirementsPath = Join-Path $JarvisDir "requirements.txt"
if (Test-Path $requirementsPath) {
    try {
        Push-Location $JarvisDir
        & $pythonCommand $pythonArgs -m pip install -r requirements.txt
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Dependencies installed successfully"
        } else {
            Write-Log "pip install failed with exit code $LASTEXITCODE" "ERROR"
            Write-Host "ERROR: Failed to install Python dependencies" -ForegroundColor Red
            exit 1
        }
        Pop-Location
    } catch {
        Write-Log "Failed to install dependencies: $_" "ERROR"
        Pop-Location
        Write-Host "ERROR: Failed to install Python dependencies" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Log "requirements.txt not found at $requirementsPath" "ERROR"
    Write-Host "ERROR: requirements.txt not found in cloned repository" -ForegroundColor Red
    exit 1
}

# ÉTAPE 4 — Saisie des clés API
Write-Log "=== Step 4: Configure API Keys ==="
$groqKeys = @()
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

# Store Groq keys
for ($i = 0; $i -lt $groqKeys.Count; $i++) {
    $varName = "GROQ_API_KEY_$($i + 1)"
    [System.Environment]::SetEnvironmentVariable($varName, $groqKeys[$i], "Machine")
    Write-Log "Groq key #$($i + 1) stored in environment variable $varName"
}

# OpenRouter key (optional)
Write-Host ""
Write-Host "Clé API OpenRouter (optionnel, appuyez sur Entrée pour passer)" -ForegroundColor Cyan
$openRouterKey = Read-Host "Clé OpenRouter"
if (-not [string]::IsNullOrWhiteSpace($openRouterKey)) {
    [System.Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", $openRouterKey.Trim(), "Machine")
    Write-Log "OpenRouter key stored in environment variable OPENROUTER_API_KEY"
}

# ÉTAPE 5 — Détection/installation Ollama
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
        
        Refresh-Path
        $ollamaInstalled = Test-Command "ollama"
    } catch {
        Write-Log "Failed to install Ollama: $_" "ERROR"
        Write-Host "WARNING: Failed to install Ollama. You can install it later from https://ollama.com" -ForegroundColor Yellow
    }
} else {
    Write-Log "Ollama already installed"
}

# Pull qwen2.5:7b model
if ($ollamaInstalled) {
    Write-Log "Pulling Ollama model qwen2.5:7b (this may take several minutes)..."
    try {
        Write-Host "Downloading qwen2.5:7b model (this may take several minutes)..." -ForegroundColor Cyan
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

# ÉTAPE 6 — Enregistrement service Windows JarvisService
Write-Log "=== Step 6: Register Windows Service ==="
$serviceName = "JarvisService"
$serviceScript = Join-Path $JarvisDir "service\windows_service.py"

if (Test-Path $serviceScript) {
    # Check if service already exists
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    
    if ($service) {
        Write-Log "Service $serviceName already exists"
        if ($service.Status -eq "Running") {
            Write-Log "Service is running"
        } else {
            Write-Log "Starting service..."
            Start-Service -Name $serviceName -ErrorAction Stop
            Write-Log "Service started"
        }
    } else {
        Write-Log "Registering service $serviceName"
        try {
            Push-Location $JarvisDir
            & $pythonCommand $pythonArgs $serviceScript install
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Service registered successfully"
                
                # Set to automatic startup
                & sc.exe config $serviceName start= auto
                Write-Log "Service configured for automatic startup"
                
                # Start the service
                Write-Log "Starting service..."
                Start-Service -Name $serviceName -ErrorAction Stop
                Write-Log "Service started"
            } else {
                Write-Log "Service registration failed with exit code $LASTEXITCODE" "ERROR"
                Write-Host "ERROR: Failed to register Windows service" -ForegroundColor Red
                exit 1
            }
            Pop-Location
        } catch {
            Write-Log "Failed to register service: $_" "ERROR"
            Pop-Location
            Write-Host "ERROR: Failed to register Windows service" -ForegroundColor Red
            exit 1
        }
    }
    
    # Verify service is running
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Write-Log "Service $serviceName is running"
    } else {
        Write-Log "Service $serviceName is not running (status: $($service.Status))" "WARN"
    }
} else {
    Write-Log "Service script not found at $serviceScript" "ERROR"
    Write-Host "ERROR: Service script not found" -ForegroundColor Red
    exit 1
}

# ÉTAPE 7 — Stockage sécurisé du PAT pour mises à jour futures
Write-Log "=== Step 7: Store PAT for Future Updates ==="
[System.Environment]::SetEnvironmentVariable("GIT_PAT_JARVIS", $GitHubPAT, "Machine")
Write-Log "PAT stored in environment variable GIT_PAT_JARVIS"

# Clear PAT from memory
$GitHubPAT = $null
Write-Log "PAT cleared from script memory"

# ÉTAPE 7 bis — Création et enregistrement de la tâche planifiée
Write-Log "=== Step 7bis: Register Scheduled Task ==="
$updateScriptPath = Join-Path $JarvisDir "bootstrap\update.ps1"

if (Test-Path $updateScriptPath) {
    $taskName = "JarvisAutoUpdate"
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
} else {
    Write-Log "Update script not found at $updateScriptPath" "WARN"
}

# ÉTAPE 8 — Résumé final
Write-Log "=== Installation Summary ==="
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "                    INSTALLATION SUMMARY" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$status = @{
    "Administrator" = $true
    "Network" = $true
    "Git" = $gitInstalled
    "Python 3.12" = $pythonInstalled
    "Jarvis Repository" = (Test-Path $JarvisDir)
    "Dependencies" = $true
    "API Keys" = ($groqKeys.Count -gt 0)
    "Ollama" = $ollamaInstalled
    "JarvisService" = ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue) -ne $null)
    "PAT Storage" = $true
    "Scheduled Task" = (Get-ScheduledTask -TaskName "JarvisAutoUpdate" -ErrorAction SilentlyContinue -ne $null)
}

foreach ($item in $status.Keys) {
    $symbol = if ($status[$item]) { "✅" } else { "❌" }
    Write-Host "$symbol $item" -ForegroundColor $(if ($status[$item]) { "Green" } else { "Red" })
}

Write-Host ""
Write-Host "Service Port: 8000" -ForegroundColor Yellow
Write-Host "Jarvis Directory: $JarvisDir" -ForegroundColor Yellow

# Try to get Tailscale IP
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

Write-Log "=== Installation Complete ==="
