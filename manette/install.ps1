# ============================================================
#   PHANTOM by The Great Corporation — Installation & Setup
#         « Satisfaction > Cout (minimal) »
# ============================================================

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   PHANTOM by The Great Corporation — Installation & Setup   " -ForegroundColor Cyan
Write-Host "         « Satisfaction > Cout (minimal) »                  " -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Verification de Python
Write-Host "[1/5] Verification de l'environnement Python..." -ForegroundColor White
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERREUR CRITIQUE] Python n'est pas installe ou absent du PATH Windows." -ForegroundColor Red
    Write-Host "Installez Python 3.10+ (avec l'option 'Add python.exe to PATH' cochee)." -ForegroundColor Yellow
    exit 1
}
$pyVersion = python --version
Write-Host "   -> $pyVersion detecte avec succes." -ForegroundColor Green

# 2. Scan du paysage local & Anti-doublons de processus
Write-Host "[2/5] Scan du paysage local et detection des doublons..." -ForegroundColor White
$existingPhantom = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*gui_app.py*" }
if ($existingPhantom) {
    Write-Host "   -> ATTENTION : Une instance de PHANTOM Server est deja en cours d'execution (PID: $($existingPhantom.ProcessId))." -ForegroundColor Yellow
    Write-Host "   -> Fermeture recommandee avant de poursuivre pour liberer les ports et les fichiers." -ForegroundColor Yellow
} else {
    Write-Host "   -> Aucun processus doublon en cours. Paysage sain." -ForegroundColor Green
}

# 3. Detection du pilote ViGEmBus
Write-Host "[3/5] Verification du pilote materiel ViGEmBus..." -ForegroundColor White
$vigemKey = Test-Path "HKLM:\SYSTEM\CurrentControlSet\Services\ViGEmBus"
if ($vigemKey) {
    Write-Host "   -> Pilote ViGEmBus detecte et actif dans le registre Windows." -ForegroundColor Green
} else {
    Write-Host "   -> ATTENTION : Pilote ViGEmBus non detecte." -ForegroundColor Yellow
    Write-Host "      L'emulation manette PC requiert ViGEmBus : https://github.com/ViGEm/ViGEmBus/releases" -ForegroundColor Gray
}

# 4. Preparation de l'environnement virtuel dedie (.venv)
Write-Host "[4/5] Initialisation de l'environnement virtuel isole..." -ForegroundColor White
$VenvDir = ".venv"
if (Test-Path -Path "venv") {
    $VenvDir = "venv"
} elseif (!(Test-Path -Path ".venv")) {
    Write-Host "   -> Creation de l'environnement virtuel .$VenvDir..." -ForegroundColor Gray
    python -m venv .venv
    $VenvDir = ".venv"
}

Write-Host "   -> Installation/Mise a jour des dependances du serveur..." -ForegroundColor Gray
& "$PWD\$VenvDir\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$PWD\$VenvDir\Scripts\python.exe" -m pip install -r "$PWD\server\requirements.txt" --quiet

# 5. Diagnostic final paysage
Write-Host "[5/5] Diagnostic de certification TGC en cours..." -ForegroundColor White
& "$PWD\$VenvDir\Scripts\python.exe" "$PWD\server\core\landscape_scanner.py"

# Creation du raccourci Bureau
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$Home\Desktop\PHANTOM Server.lnk")
$Shortcut.TargetPath = "$PWD\$VenvDir\Scripts\pythonw.exe"
$Shortcut.Arguments = "`"$PWD\server\gui_app.py`""
$Shortcut.WorkingDirectory = "$PWD"
$Shortcut.Save()

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " INSTALLATION TERMINEE AVEC SUCCES !" -ForegroundColor Green
Write-Host " Raccourci cree sur votre Bureau : PHANTOM Server" -ForegroundColor Green
Write-Host " Double-cliquez pour demarrer la manette invisible TGC." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green


