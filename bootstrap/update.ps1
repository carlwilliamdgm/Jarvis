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

try {
    Write-Log "=== Starting Jarvis Auto-Update ==="
    
    # Retrieve PAT from environment variable
    $pat = [System.Environment]::GetEnvironmentVariable("GIT_PAT_JARVIS", "Machine")
    
    if (-not $pat) {
        Write-Log "GIT_PAT_JARVIS introuvable — mise à jour impossible" "ERROR"
        exit 1
    }
    
    Push-Location $JarvisDir
    
    # Get current commit hash
    $currentHash = git rev-parse HEAD 2>&1
    Write-Log "Current commit: $currentHash"
    
    # Perform git pull with PAT via GIT_ASKPASS (never in URL, args, or logs)
    $pullExit = Invoke-GitWithPAT -GitArgs @("pull", "origin", "main") -Pat $pat
    
    if ($pullExit -eq 0) {
        $newHash = git rev-parse HEAD 2>&1
        Write-Log "New commit: $newHash"
        
        if ($currentHash -eq $newHash) {
            Write-Log "OK — no changes detected"
        } else {
            Write-Log "Changes detected — restarting $agentTaskName"
            $agentTask = Get-ScheduledTask -TaskName $agentTaskName -ErrorAction Stop
            if ($agentTask.State -eq "Running") {
                Stop-ScheduledTask -TaskName $agentTaskName
                Start-Sleep -Seconds 2
            }
            Start-ScheduledTask -TaskName $agentTaskName
            Write-Log "Update applied — commit $currentHash → $newHash, task restarted"
        }
    } else {
        Write-Log "Git pull failed — task unchanged, reason: git error" "ERROR"
    }
    
    Pop-Location
} catch {
    Write-Log "Update failed: $_" "ERROR"
    exit 1
}
