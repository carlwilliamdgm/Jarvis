$JarvisDir = [System.Environment]::GetEnvironmentVariable("JARVIS_INSTALL_DIR", "Machine")
if (-not $JarvisDir) {
    $JarvisDir = Join-Path $env:USERPROFILE "Jarvis"
}
$AgentTaskName = "JarvisAgent"
$LogPath = Join-Path $JarvisDir "bootstrap\update.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $logLine -Encoding UTF8
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
    
    # Perform git pull with PAT via http.extraHeader (not stored in remote)
    git -c "http.extraHeader=Authorization: token $pat" pull origin main
    
    if ($LASTEXITCODE -eq 0) {
        $newHash = git rev-parse HEAD 2>&1
        Write-Log "New commit: $newHash"
        
        if ($currentHash -eq $newHash) {
            Write-Log "OK — no changes detected"
        } else {
            Write-Log "Changes detected — restarting $AgentTaskName"
            $agentTask = Get-ScheduledTask -TaskName $AgentTaskName -ErrorAction Stop
            if ($agentTask.State -eq "Running") {
                Stop-ScheduledTask -TaskName $AgentTaskName
                Start-Sleep -Seconds 2
            }
            Start-ScheduledTask -TaskName $AgentTaskName
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
