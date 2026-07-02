param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubPAT
)

# Bootstrap installation script for Jarvis
# Usage: powershell.exe -ExecutionPolicy Bypass -File bootstrap\install.ps1 -GitHubPAT <your_pat>
# Requires Administrator privileges

$ErrorActionPreference = "Stop"
$LogPath = Join-Path $PSScriptRoot "bootstrap_install.log"
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

# Step 1: Detect/install Python 3.12
Write-Log "=== Step 1: Python 3.12 Detection/Installation ==="
$pythonInstalled = $false
$pythonPath = $null

# Check for python in standard locations
$standardPaths = @(
    "C:\Program Files\Python312\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe"
)

foreach ($path in $standardPaths) {
    if (Test-Path $path) {
        $pythonPath = $path
        $pythonInstalled = $true
        Write-Log "Python 3.12 found at: $path"
        break
    }
}

# Check via py launcher or python command
if (-not $pythonInstalled) {
    if (Test-Command "py") {
        $version = & py -3.12 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonInstalled = $true
            $pythonPath = "py -3.12"
            Write-Log "Python 3.12 found via py launcher: $version"
        }
    } elseif (Test-Command "python") {
        $version = & python --version 2>&1
        if ($version -match "3\.12") {
            $pythonInstalled = $true
            $pythonPath = "python"
            Write-Log "Python 3.12 found via python command: $version"
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
Write-Log "=== Step 2: Clone Jarvis Repository ==="
$repoUrl = "https://${GitHubPAT}@github.com/carlwilliamdgm/Jarvis.git"

if (Test-Path $JarvisDir) {
    # Check if it's a valid git repo
    $gitDir = Join-Path $JarvisDir ".git"
    if (Test-Path $gitDir) {
        Write-Log "Repository already exists. Performing git pull..."
        try {
            Push-Location $JarvisDir
            $currentHash = & git rev-parse HEAD 2>&1
            Write-Log "Current commit: $currentHash"
            
            & git pull origin main
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
        & git clone $repoUrl $JarvisDir
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Git clone failed" "ERROR"
            throw "Failed to clone repository"
        }
        Write-Log "Repository cloned successfully"
    }
} else {
    Write-Log "Cloning repository to $JarvisDir"
    & git clone $repoUrl $JarvisDir
    if ($LASTEXITCODE -ne 0) {
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

# Step 4: Configure API keys
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
# Step 6: Register Windows service JarvisService
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
                
                # Set to automatic startup
                & sc.exe config $serviceName start= auto
                Write-Log "Service configured for automatic startup"
                
                # Start the service
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
    
    # Verify service is running
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

# Step 7: Store PAT securely for future updates
Write-Log "=== Step 7: Store PAT for Future Updates ==="
# Use Windows Credential Manager
try {
    Write-Log "Storing PAT in Windows Credential Manager"
    & cmdkey /generic:JarvisGitPAT /user:GitHubPAT /pass:$GitHubPAT
    if ($LASTEXITCODE -eq 0) {
        Write-Log "PAT stored successfully in Credential Manager"
    } else {
        Write-Log "Failed to store PAT in Credential Manager (exit code $LASTEXITCODE)" "WARN"
        # Fallback to environment variable
        [System.Environment]::SetEnvironmentVariable("GIT_PAT_JARVIS", $GitHubPAT, "Machine")
        Write-Log "PAT stored in environment variable GIT_PAT_JARVIS (fallback)"
    }
} catch {
    Write-Log "Failed to store PAT: $_" "WARN"
    # Fallback to environment variable
    [System.Environment]::SetEnvironmentVariable("GIT_PAT_JARVIS", $GitHubPat, "Machine")
    Write-Log "PAT stored in environment variable GIT_PAT_JARVIS (fallback)"
}

# Step 8: Display summary
Write-Log "=== Installation Summary ==="
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "                    INSTALLATION SUMMARY" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$status = @{ "Python 3.12" = $pythonInstalled; "Jarvis Repository" = (Test-Path $JarvisDir); "Dependencies" = $true; "API Keys" = ($groqKeys.Count -gt 0); "Ollama" = $ollamaInstalled; "JarvisService" = ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue) -ne $null); "PAT Storage" = $true }

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

# Create update.ps1 script
Write-Log "=== Creating update.ps1 script ==="
$updateScript = @'
$JarvisDir = Join-Path $env:USERPROFILE "Jarvis"
$LogPath = Join-Path $JarvisDir "bootstrap\update.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $logLine -Encoding UTF8
}

try {
    Write-Log "=== Starting Jarvis Auto-Update ==="
    
    # Retrieve PAT from Credential Manager
    $pat = $null
    try {
        $credOutput = cmdkey /list:JarvisGitPAT 2>&1
        if ($credOutput -match "Password\s*:\s*(.+)") {
            $pat = $matches[1].Trim()
        }
    } catch {
        # Fallback to environment variable
        $pat = [System.Environment]::GetEnvironmentVariable("GIT_PAT_JARVIS", "Machine")
    }
    
    if (-not $pat) {
        Write-Log "PAT not found in Credential Manager or environment" "ERROR"
        exit 1
    }
    
    Push-Location $JarvisDir
    
    # Get current commit hash
    $currentHash = git rev-parse HEAD 2>&1
    Write-Log "Current commit: $currentHash"
    
    # Perform git pull
    $repoUrl = "https://${pat}@github.com/carlwilliamdgm/Jarvis.git"
    git pull origin main
    
    if ($LASTEXITCODE -eq 0) {
        $newHash = git rev-parse HEAD 2>&1
        Write-Log "New commit: $newHash"
        
        if ($currentHash -eq $newHash) {
            Write-Log "OK — no changes detected"
        } else {
            Write-Log "Changes detected — restarting JarvisService"
            
            # Stop and restart service
            Stop-Service -Name JarvisService -Force
            Start-Sleep -Seconds 5
            Start-Service -Name JarvisService
            
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

Write-Log "=== Installation Complete ==="