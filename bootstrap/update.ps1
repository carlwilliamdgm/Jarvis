$JarvisDir = [System.Environment]::GetEnvironmentVariable("JARVIS_INSTALL_DIR", "Machine")
if (-not $JarvisDir) {
    $JarvisDir = Join-Path $env:USERPROFILE "Jarvis"
}
$agentTaskName = "JarvisAgent"
$LogPath = Join-Path $JarvisDir "bootstrap\update.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $logLine -Encoding UTF8
    Write-Host $logLine
}

function Resolve-PythonPath {
    param([string]$BaseDir)

    # 1. Environment variables (Process then Machine)
    if ($env:JARVIS_PYTHON_EXE -and (Test-Path $env:JARVIS_PYTHON_EXE)) {
        return $env:JARVIS_PYTHON_EXE
    }
    $machinePython = [System.Environment]::GetEnvironmentVariable("JARVIS_PYTHON_EXE", "Machine")
    if ($machinePython -and (Test-Path $machinePython)) {
        return $machinePython
    }

    # 2. Virtual environments
    $venvCandidates = @(
        (Join-Path $BaseDir ".venv\Scripts\python.exe"),
        (Join-Path $BaseDir "venv\Scripts\python.exe")
    )
    foreach ($candidate in $venvCandidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    # 3. Standard paths
    $standardPaths = @(
        "C:\Program Files\Python312\python.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )
    foreach ($path in $standardPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    # 4. PATH command or py launcher
    $cmdPython = Get-Command "python" -ErrorAction SilentlyContinue
    if ($cmdPython) {
        return $cmdPython.Source
    }

    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        $resolved = (& py -3.12 -c "import sys; print(sys.executable)" 2>&1)
        if ($LASTEXITCODE -eq 0 -and (Test-Path ($resolved.Trim()))) {
            return $resolved.Trim()
        }
    }

    return "python.exe"
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

function Invoke-Rollback {
    param(
        [string]$TargetHash,
        [string]$PythonExe,
        [string]$Reason
    )
    Write-Log "ROLLBACK TRIGGERED: $Reason" "WARN"
    Write-Log "Reverting git repository to commit $TargetHash..." "WARN"
    & git reset --hard $TargetHash
    if (Test-Path "requirements.txt") {
        Write-Log "Re-synchronizing dependencies for restored commit $TargetHash..." "WARN"
        & $PythonExe -m pip install -r requirements.txt --quiet
    }
    Write-Log "Rollback completed to commit $TargetHash. Service restart aborted." "WARN"
}

try {
    Write-Log "=== Starting Jarvis Auto-Update ==="
    
    # Retrieve PAT from environment variable
    $pat = [System.Environment]::GetEnvironmentVariable("GIT_PAT_JARVIS", "Machine")
    
    if (-not $pat) {
        Write-Log "GIT_PAT_JARVIS introuvable — mise à jour impossible" "ERROR"
        exit 1
    }
    
    Push-Location $JarvisDir
    $pythonExe = Resolve-PythonPath -BaseDir $JarvisDir
    Write-Log "Resolved Python executable: $pythonExe"
    
    # Get current commit hash
    $currentHash = (& git rev-parse HEAD 2>&1).Trim()
    Write-Log "Current commit: $currentHash"
    
    # Perform git pull with PAT via GIT_ASKPASS (never in URL, args, or logs)
    $pullExit = Invoke-GitWithPAT -GitArgs @("pull", "origin", "main") -Pat $pat
    
    if ($pullExit -eq 0) {
        $newHash = (& git rev-parse HEAD 2>&1).Trim()
        Write-Log "New commit: $newHash"
        
        if ($currentHash -eq $newHash) {
            Write-Log "OK — no changes detected"
        } else {
            Write-Log "Changes detected ($currentHash -> $newHash). Verifying update integrity..."
            
            # Step A: Install/verify dependencies
            $reqPath = Join-Path $JarvisDir "requirements.txt"
            if (Test-Path $reqPath) {
                Write-Log "Checking dependencies via pip install -r requirements.txt..."
                & $pythonExe -m pip install -r requirements.txt
                if ($LASTEXITCODE -ne 0) {
                    Invoke-Rollback -TargetHash $currentHash -PythonExe $pythonExe -Reason "pip install failed with exit code $LASTEXITCODE"
                    Pop-Location
                    exit 1
                }
                Write-Log "Dependencies successfully verified"
            }
            
            # Step B: Run smoke test suite before restarting service
            Write-Log "Running smoke tests..."
            $smokeRun = & $pythonExe -m pytest -m smoke --tb=short 2>&1
            $testExitCode = $LASTEXITCODE
            
            # If pytest is not installed in the current environment, fallback to unittest on safety/smoke modules
            if ($testExitCode -ne 0 -and $smokeRun -match "No module named pytest") {
                Write-Log "pytest not available in runtime, executing unittest smoke suite..." "WARN"
                $smokeRun = & $pythonExe -m unittest discover -s tests -p "test_*.py" 2>&1
                $testExitCode = $LASTEXITCODE
            }
            
            if ($testExitCode -ne 0) {
                Write-Log "Smoke tests FAILED:`n$smokeRun" "ERROR"
                Invoke-Rollback -TargetHash $currentHash -PythonExe $pythonExe -Reason "Smoke tests failed with exit code $testExitCode"
                Pop-Location
                exit 1
            }
            Write-Log "Smoke tests PASSED successfully"
            
            # Step C: Restart scheduled task / agent
            Write-Log "Restarting $agentTaskName scheduled task..."
            $agentTask = Get-ScheduledTask -TaskName $agentTaskName -ErrorAction SilentlyContinue
            if ($agentTask) {
                if ($agentTask.State -eq "Running") {
                    Stop-ScheduledTask -TaskName $agentTaskName
                    Start-Sleep -Seconds 2
                }
                Start-ScheduledTask -TaskName $agentTaskName
                Write-Log "Update successfully applied — commit $currentHash -> $newHash, task restarted"
            } else {
                Write-Log "Update applied — commit $currentHash -> $newHash (task $agentTaskName not registered)" "WARN"
            }
        }
    } else {
        Write-Log "Git pull failed — task unchanged, reason: git error" "ERROR"
    }
    
    Pop-Location
} catch {
    Write-Log "Update script unhandled exception: $_" "ERROR"
    exit 1
}
