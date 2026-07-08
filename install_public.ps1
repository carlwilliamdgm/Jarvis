# Jarvis public bootstrap.
# Responsibilities: capture PAT, clone private repo, disable interactive Git auth, hand off.

$ErrorActionPreference = "Stop"

$GitHubPAT = $null
while (-not $GitHubPAT) {
    $GitHubPAT = Read-Host "Entrez votre Personal Access Token GitHub (scope: repo sur carlwilliamdgm/Jarvis)"
    if ([string]::IsNullOrWhiteSpace($GitHubPAT)) {
        Write-Host "Le PAT ne peut pas etre vide. Veuillez reessayer." -ForegroundColor Yellow
    }
}

$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"
$env:GIT_ASKPASS = ""
$env:SSH_ASKPASS = ""

$repoUrlWithPat = "https://${GitHubPAT}@github.com/carlwilliamdgm/Jarvis.git"
$repoUrlClean = "https://github.com/carlwilliamdgm/Jarvis.git"
$handoffDir = Join-Path $env:TEMP "jarvis-private-install"

if (Test-Path $handoffDir) {
    Remove-Item $handoffDir -Recurse -Force
}

git -c credential.helper= -c core.askPass= clone $repoUrlWithPat $handoffDir
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
    $GitHubPAT = $null
    $repoUrlWithPat = $null
}
