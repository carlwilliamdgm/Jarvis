#Requires -Version 5.1
<#
.SYNOPSIS
    Test d'intégration runtime ACL TLS pour Assert-OperatorTlsKeyAcl.

.DESCRIPTION
    Valide le comportement de Assert-OperatorTlsKeyAcl (définie dans bootstrap/install.ps1)
    sur un certificat TLS auto-signé temporaire créé dans un dossier temporaire.

    Scénarios testés :
      T01 - Clé TLS avec ACL correctes (propriétaire=CurrentUser, seul CurrentUser/SYSTEM/Admins) => PASS
      T02 - Clé TLS avec ACE Allow supplémentaire pour un SID non approuvé => FAIL attendu
      T03 - Dossier parent avec ACE Allow mutable pour un SID non approuvé => FAIL attendu
      T04 - Chemin est un répertoire => FAIL attendu
      T05 - Fichier non-existant => FAIL attendu
      T06 - Clé TLS est un reparse point (junction) => FAIL attendu

    Compatibilité : Win10 21H2+, Win10 22H2, Win11 22H2, Win11 23H2 (sans élévation UAC)
    Droits requis  : Utilisateur standard (pas d'élévation requise pour créer des fichiers temp)

.NOTES
    Auteur  : Security Engineer — GreatOS / J.A.R.V.I.S.
    Date    : 2026-10-14
    Bloquer : Un reparse point sur le DOSSIER temp lui-même est hors portée du test sans UAC
              (mklink /J requiert un accès privilégié sur certaines configs).
              Le test T06 crée un lien symbolique de fichier — nécessite SeCreateSymbolicLinkPrivilege
              ou le mode développeur Windows activé ; il est marqué SKIP si indisponible.

.USAGE
    # Sans élévation (tests T01-T05 garantis) :
    powershell.exe -ExecutionPolicy Bypass -File tests\test_acl_tls_runtime.ps1

    # Intégration CI (sortie TAP-like) :
    powershell.exe -ExecutionPolicy Bypass -File tests\test_acl_tls_runtime.ps1 -Verbose
#>

param(
    [switch]$FailFast,
    [switch]$KeepArtifacts   # Ne pas nettoyer en cas d'échec (debug)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Importer Assert-OperatorTlsKeyAcl depuis install.ps1 ───────────────────────
$installScript = Join-Path $PSScriptRoot "..\bootstrap\install.ps1"
if (-not (Test-Path $installScript)) {
    Write-Error "bootstrap\install.ps1 introuvable : $installScript"
    exit 1
}

# Charger uniquement les fonctions sans exécuter le corps principal du script.
# On extrait et évalue uniquement le bloc de la fonction cible.
$scriptContent = Get-Content $installScript -Raw -Encoding UTF8

# Extraire la fonction Assert-OperatorTlsKeyAcl par regex multi-lignes
if ($scriptContent -notmatch '(?ms)(function Assert-OperatorTlsKeyAcl\s*\{.*?\n\})') {
    Write-Error "Impossible d'extraire Assert-OperatorTlsKeyAcl depuis install.ps1"
    exit 1
}
$funcBlock = $Matches[1]

# Évaluer uniquement la définition de la fonction dans la portée courante
try {
    Invoke-Expression $funcBlock
} catch {
    Write-Error "Erreur lors du chargement de Assert-OperatorTlsKeyAcl : $_"
    exit 1
}

if (-not (Get-Command "Assert-OperatorTlsKeyAcl" -ErrorAction SilentlyContinue)) {
    Write-Error "Assert-OperatorTlsKeyAcl n'est pas disponible après chargement."
    exit 1
}

# ── Infrastructure de test ─────────────────────────────────────────────────────
$totalTests   = 0
$passedTests  = 0
$failedTests  = 0
$skippedTests = 0
$testResults  = @()

function Invoke-Test {
    param(
        [string]$Name,
        [scriptblock]$Body,
        [switch]$ExpectFailure,   # Le test doit lever une exception
        [switch]$Skip
    )

    $script:totalTests++

    if ($Skip) {
        Write-Host "  [SKIP] $Name" -ForegroundColor DarkYellow
        $script:skippedTests++
        $script:testResults += [pscustomobject]@{ Name=$Name; Result="SKIP"; Detail="" }
        return
    }

    Write-Host "  [RUN ] $Name" -ForegroundColor Cyan -NoNewline

    try {
        $errorDetail = ""
        & $Body
        if ($ExpectFailure) {
            Write-Host " => FAIL (exception attendue mais non levée)" -ForegroundColor Red
            $script:failedTests++
            $script:testResults += [pscustomobject]@{ Name=$Name; Result="FAIL"; Detail="exception attendue mais non levée" }
            if ($FailFast) { throw "FAIL_FAST" }
        } else {
            Write-Host " => PASS" -ForegroundColor Green
            $script:passedTests++
            $script:testResults += [pscustomobject]@{ Name=$Name; Result="PASS"; Detail="" }
        }
    } catch {
        if ($_ -eq "FAIL_FAST") { throw }
        if ($ExpectFailure) {
            Write-Host " => PASS (exception attendue : $($_.Exception.Message.Split([char]0x0A)[0].Trim()))" -ForegroundColor Green
            $script:passedTests++
            $script:testResults += [pscustomobject]@{ Name=$Name; Result="PASS"; Detail="exception=$($_.Exception.Message.Split([char]0x0A)[0].Trim())" }
        } else {
            Write-Host " => FAIL : $($_.Exception.Message.Split([char]0x0A)[0].Trim())" -ForegroundColor Red
            $script:failedTests++
            $script:testResults += [pscustomobject]@{ Name=$Name; Result="FAIL"; Detail=$_.Exception.Message }
            if ($FailFast) { throw "FAIL_FAST" }
        }
    }
}

# ── Création d'un certificat TLS auto-signé temporaire ────────────────────────
#
# New-SelfSignedCertificate est disponible depuis Win8.1 / Win10 (pki module).
# Compatibilité : Win10 21H2+ ✓, Win10 22H2 ✓, Win11 22H2 ✓, Win11 23H2 ✓
#
$tempRoot   = Join-Path $env:TEMP "jarvis_acl_test_$PID"
$tempKeyDir = Join-Path $tempRoot "certs"
$tempKeyFile= Join-Path $tempKeyDir "test_operator.key"  # Fichier factice représentant la clé privée

$cleanupPaths = @($tempRoot)

function Initialize-TestEnvironment {
    New-Item -ItemType Directory -Path $tempRoot    -Force | Out-Null
    New-Item -ItemType Directory -Path $tempKeyDir  -Force | Out-Null

    # Créer un fichier factice représentant la clé privée (contenu aléatoire, non sensible)
    $dummyContent = [System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(256))
    Set-Content -Path $tempKeyFile -Value "-----BEGIN PRIVATE KEY-----`n$dummyContent`n-----END PRIVATE KEY-----" -Encoding ASCII

    # Récupérer le SID du compte courant
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid  = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")
    $adminsSid  = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")

    # Appliquer ACL restrictive sur le fichier clé : CurrentUser/SYSTEM/Admins en lecture seule
    $acl = New-Object System.Security.AccessControl.FileSecurity

    # Désactiver l'héritage et supprimer les ACE héritées
    $acl.SetAccessRuleProtection($true, $false)

    # ACE pour CurrentUser (FullControl pour permettre le test de lecture ACL)
    $ruleUser   = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $currentSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    # ACE pour SYSTEM (Read)
    $ruleSystem = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $systemSid,
        [System.Security.AccessControl.FileSystemRights]::Read,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    # ACE pour Administrateurs (Read)
    $ruleAdmins = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $adminsSid,
        [System.Security.AccessControl.FileSystemRights]::Read,
        [System.Security.AccessControl.AccessControlType]::Allow
    )

    $acl.AddAccessRule($ruleUser)
    $acl.AddAccessRule($ruleSystem)
    $acl.AddAccessRule($ruleAdmins)

    # Définir CurrentUser comme propriétaire
    $acl.SetOwner($currentSid)

    Set-Acl -LiteralPath $tempKeyFile -AclObject $acl
}

function Remove-TestArtifacts {
    if ($KeepArtifacts) {
        Write-Host "`n  [INFO] Artefacts conservés dans : $tempRoot" -ForegroundColor DarkYellow
        return
    }
    foreach ($p in $cleanupPaths) {
        if (Test-Path $p) {
            try { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

# ── Helpers ACL ───────────────────────────────────────────────────────────────
function Add-UnauthorizedAce {
    param([string]$Path, [System.Security.AccessControl.FileSystemRights]$Rights)

    # Utilise un SID de service bien connu non approuvé : Network Service (S-1-5-20)
    $netSvcSid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-20")

    if ((Get-Item -LiteralPath $Path -Force).PSIsContainer) {
        $acl  = Get-Acl -LiteralPath $Path
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $netSvcSid, $Rights,
            [System.Security.AccessControl.InheritanceFlags]::None,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } else {
        $acl  = Get-Acl -LiteralPath $Path
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $netSvcSid, $Rights,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    }
}

function Remove-UnauthorizedAce {
    param([string]$Path)
    $netSvcSid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-20")
    $acl = Get-Acl -LiteralPath $Path
    $rules = $acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]) |
        Where-Object { $_.IdentityReference.Value -eq $netSvcSid.Value }
    foreach ($r in $rules) { $acl.RemoveAccessRule($r) | Out-Null }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Test-SymbolicLinkAvailable {
    # Teste si la création de lien symbolique est disponible (mode développeur ou SeCreateSymbolicLinkPrivilege)
    $testLink = Join-Path $env:TEMP "jarvis_symlink_probe_$PID"
    $testTarget = Join-Path $env:TEMP "jarvis_symlink_target_$PID.txt"
    try {
        Set-Content $testTarget -Value "probe" -Encoding ASCII -ErrorAction Stop
        & cmd /c mklink "$testLink" "$testTarget" 2>$null | Out-Null
        $ok = Test-Path $testLink
        return $ok
    } catch {
        return $false
    } finally {
        Remove-Item $testLink    -Force -ErrorAction SilentlyContinue
        Remove-Item $testTarget  -Force -ErrorAction SilentlyContinue
    }
}

# ── EXÉCUTION DES TESTS ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════"
Write-Host "  Test d'intégration runtime ACL TLS — Assert-OperatorTlsKeyAcl"
Write-Host "═══════════════════════════════════════════════════════════"
Write-Host "  Environnement  : $([System.Environment]::OSVersion.VersionString)"
Write-Host "  Utilisateur    : $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)"
Write-Host "  PID            : $PID"
Write-Host "  Dossier temp   : $tempRoot"
Write-Host ""

try {
    Initialize-TestEnvironment
} catch {
    Write-Host "ERREUR lors de l'initialisation de l'environnement de test : $_" -ForegroundColor Red
    exit 2
}

# ── T01 : ACL correctes — doit PASSER ────────────────────────────────────────
Invoke-Test -Name "T01 — Clé TLS avec ACL correctes (propriétaire=CurrentUser, ACE approuvés uniquement)" -Body {
    Assert-OperatorTlsKeyAcl -KeyPath $tempKeyFile
}

# ── T02 : ACE Allow non approuvée sur le fichier clé — doit ÉCHOUER ──────────
Invoke-Test -Name "T02 — Clé TLS avec ACE Allow pour Network Service (non approuvé)" -ExpectFailure -Body {
    try {
        Add-UnauthorizedAce -Path $tempKeyFile -Rights ([System.Security.AccessControl.FileSystemRights]::Read)
        Assert-OperatorTlsKeyAcl -KeyPath $tempKeyFile
    } finally {
        Remove-UnauthorizedAce -Path $tempKeyFile
    }
}

# ── T03 : ACE Allow mutable sur le dossier parent — doit ÉCHOUER ─────────────
Invoke-Test -Name "T03 — Dossier parent avec WriteData (mutable) pour Network Service (non approuvé)" -ExpectFailure -Body {
    try {
        Add-UnauthorizedAce -Path $tempKeyDir -Rights ([System.Security.AccessControl.FileSystemRights]::WriteData)
        Assert-OperatorTlsKeyAcl -KeyPath $tempKeyFile
    } finally {
        Remove-UnauthorizedAce -Path $tempKeyDir
    }
}

# ── T04 : Chemin est un répertoire — doit ÉCHOUER ────────────────────────────
Invoke-Test -Name "T04 — Le chemin cible est un répertoire (pas un fichier)" -ExpectFailure -Body {
    Assert-OperatorTlsKeyAcl -KeyPath $tempKeyDir
}

# ── T05 : Fichier inexistant — doit ÉCHOUER ───────────────────────────────────
Invoke-Test -Name "T05 — Fichier TLS inexistant" -ExpectFailure -Body {
    Assert-OperatorTlsKeyAcl -KeyPath (Join-Path $tempKeyDir "nonexistent.key")
}

# ── T06 : Lien symbolique vers la clé — doit ÉCHOUER (reparse point) ─────────
$symLinkAvailable = Test-SymbolicLinkAvailable
Invoke-Test -Name "T06 — Clé TLS est un lien symbolique (reparse point)" -ExpectFailure `
            -Skip:(-not $symLinkAvailable) -Body {

    $realFile = Join-Path $tempKeyDir "real_key.key"
    $symlinkFile = Join-Path $tempKeyDir "symlink_key.key"
    try {
        Copy-Item $tempKeyFile $realFile -Force
        & cmd /c mklink "$symlinkFile" "$realFile" 2>$null | Out-Null
        if (-not (Test-Path $symlinkFile)) {
            throw "Impossible de créer le lien symbolique (mode développeur non activé ?)"
        }
        Assert-OperatorTlsKeyAcl -KeyPath $symlinkFile
    } finally {
        Remove-Item $symlinkFile -Force -ErrorAction SilentlyContinue
        Remove-Item $realFile    -Force -ErrorAction SilentlyContinue
    }
}

# ── T07 : Clé TLS avec ACE ReadData seulement sur dossier parent — doit PASSER ─
# (Les droits en lecture seule sur les parents sont autorisés ; seuls les droits
#  de mutation sont bloqués pour les non-approuvés.)
Invoke-Test -Name "T07 — Dossier parent avec ReadData uniquement pour Network Service (lecture seule, admis)" -Body {
    try {
        Add-UnauthorizedAce -Path $tempKeyDir -Rights ([System.Security.AccessControl.FileSystemRights]::ReadData)
        Assert-OperatorTlsKeyAcl -KeyPath $tempKeyFile
    } finally {
        Remove-UnauthorizedAce -Path $tempKeyDir
    }
}

# ── T08 : Clé TLS avec ACE ChangePermissions sur le dossier parent — doit ÉCHOUER ─
Invoke-Test -Name "T08 — Dossier parent avec ChangePermissions pour Network Service (non approuvé)" -ExpectFailure -Body {
    try {
        Add-UnauthorizedAce -Path $tempKeyDir -Rights ([System.Security.AccessControl.FileSystemRights]::ChangePermissions)
        Assert-OperatorTlsKeyAcl -KeyPath $tempKeyFile
    } finally {
        Remove-UnauthorizedAce -Path $tempKeyDir
    }
}

# ── T09 : Clé TLS avec ACE TakeOwnership sur le dossier parent — doit ÉCHOUER ─
Invoke-Test -Name "T09 — Dossier parent avec TakeOwnership pour Network Service (non approuvé)" -ExpectFailure -Body {
    try {
        Add-UnauthorizedAce -Path $tempKeyDir -Rights ([System.Security.AccessControl.FileSystemRights]::TakeOwnership)
        Assert-OperatorTlsKeyAcl -KeyPath $tempKeyFile
    } finally {
        Remove-UnauthorizedAce -Path $tempKeyDir
    }
}

# ── NETTOYAGE ─────────────────────────────────────────────────────────────────
Remove-TestArtifacts

# ── RÉSUMÉ ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════"
Write-Host "  RÉSULTATS" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════"
foreach ($r in $testResults) {
    $color = switch ($r.Result) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        "SKIP" { "DarkYellow" }
        default { "White" }
    }
    $detail = if ($r.Detail) { " — $($r.Detail.Split([char]0x0A)[0].Trim())" } else { "" }
    Write-Host ("  [{0,-4}] {1}{2}" -f $r.Result, $r.Name, $detail) -ForegroundColor $color
}
Write-Host ""
Write-Host ("  Total: {0}  |  PASS: {1}  |  FAIL: {2}  |  SKIP: {3}" -f `
    $totalTests, $passedTests, $failedTests, $skippedTests) -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════"

if ($failedTests -gt 0) {
    Write-Host "`n  RÉSULTAT GLOBAL : ÉCHEC ($failedTests test(s) en erreur)" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n  RÉSULTAT GLOBAL : SUCCÈS" -ForegroundColor Green
    exit 0
}
