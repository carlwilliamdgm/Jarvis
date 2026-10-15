# Script pour mettre à jour la tâche planifiée JarvisAgent avec exécution en arrière-plan
# Ce script doit être exécuté avec des droits d'administrateur
#
# CORRECTIF BINDING (Option B) :
#   jarvis_hidden.ps1 accepte -HostAddress avec la valeur par défaut "127.0.0.1".
#   Si ce paramètre n'est pas transmis, le serveur n'écoute que sur localhost et
#   devient inaccessible depuis le tailnet (Tailscale).
#   On passe toujours explicitement -HostAddress "0.0.0.0" pour reproduire le
#   comportement de bootstrap\install.ps1 et garantir l'accès réseau distant.

$projectRoot = $PSScriptRoot
$jarvisHiddenScript = Join-Path $projectRoot "jarvis_hidden.ps1"

# Résoudre l'interpréteur Python : venv du projet en priorité, sinon python du PATH
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonExe  = if (Test-Path $venvPython -PathType Leaf) { $venvPython } else { "python" }

# NOTE : -HostAddress "0.0.0.0" est OBLIGATOIRE pour l'accès Tailscale.
#        Ne jamais supprimer ce paramètre : jarvis_hidden.ps1 retombe sinon sur 127.0.0.1.
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$jarvisHiddenScript`" -PythonExe `"$pythonExe`" -HostAddress `"0.0.0.0`"" `
    -WorkingDirectory $projectRoot
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Set-ScheduledTask -TaskName JarvisAgent -Action $action -Settings $settings

Write-Host "Tâche planifiée JarvisAgent mise à jour avec succès (binding 0.0.0.0, accès Tailscale préservé)."
Write-Host "Les logs uvicorn seront redirigés vers $projectRoot\logs\uvicorn.log"