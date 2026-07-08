# Jarvis public bootstrap.
# Responsibilities: capture PAT, clone private repo, disable interactive Git auth, hand off.

$ErrorActionPreference = "Stop"

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
        Write-Host "Git deja installe."
        return
    }

    Write-Host "Git introuvable. Installation de Git for Windows..."
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

        Write-Host "Git installe avec succes."
    } finally {
        Remove-Item $gitInstallerPath -Force -ErrorAction SilentlyContinue
    }
}

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Ce script doit etre execute en tant qu'Administrateur." -ForegroundColor Red
    Write-Host "Relancez PowerShell en mode Administrateur, puis reessayez." -ForegroundColor Red
    throw "Privileges administrateur requis"
}

Update-ProcessPathFromRegistry
Install-GitIfMissing

$GitHubPAT = $null
while (-not $GitHubPAT) {
    $GitHubPAT = Read-Host "Entrez votre Personal Access Token GitHub (scope: repo sur carlwilliamdgm/Jarvis)"
    if ([string]::IsNullOrWhiteSpace($GitHubPAT)) {
        Write-Host "Le PAT ne peut pas etre vide. Veuillez reessayer." -ForegroundColor Yellow
    }
}

$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"
$env:SSH_ASKPASS = ""

$repoUrlClean = "https://github.com/carlwilliamdgm/Jarvis.git"
$handoffDir = Join-Path $env:TEMP "jarvis-private-install"

if (Test-Path $handoffDir) {
    Remove-Item $handoffDir -Recurse -Force
}

$askPassPath = Join-Path $env:TEMP "jarvis_public_askpass_$PID.cmd"
"@echo off`r`necho %1 | findstr /I `"Username`" >nul`r`nif %ERRORLEVEL%==0 (`r`n  echo x-access-token`r`n) else (`r`n  echo %JARVIS_PUBLIC_GIT_PAT%`r`n)" | Out-File -FilePath $askPassPath -Encoding ASCII -Force
$previousAskPass = $env:GIT_ASKPASS
$env:GIT_ASKPASS = $askPassPath
$env:JARVIS_PUBLIC_GIT_PAT = $GitHubPAT

try {
    git -c credential.helper= clone $repoUrlClean $handoffDir
    if ($LASTEXITCODE -ne 0) {
        throw "Impossible de cloner le repo prive Jarvis. Verifiez le PAT et l'acces reseau."
    }

    Push-Location $handoffDir
    try {
        git remote set-url origin $repoUrlClean
        $privateInstall = Join-Path $handoffDir "bootstrap\install.ps1"
        if (-not (Test-Path $privateInstall)) {
            throw "Script d'installation prive introuvable: $privateInstall"
        }

        powershell.exe -ExecutionPolicy Bypass -File $privateInstall -GitHubPAT $GitHubPAT
    } finally {
        Pop-Location
    }
} finally {
    $GitHubPAT = $null
    Remove-Item $askPassPath -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\JARVIS_PUBLIC_GIT_PAT -ErrorAction SilentlyContinue
    if ($null -ne $previousAskPass) { $env:GIT_ASKPASS = $previousAskPass } else { Remove-Item Env:\GIT_ASKPASS -ErrorAction SilentlyContinue }
}
