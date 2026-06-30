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
