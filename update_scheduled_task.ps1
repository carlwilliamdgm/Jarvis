# Script pour mettre à jour la tâche planifiée JarvisAgent avec exécution en arrière-plan
# Ce script doit être exécuté avec des droits d'administrateur

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"C:\Users\Carl\Jarvis\jarvis_hidden.ps1`"" -WorkingDirectory "C:\Users\Carl\Jarvis"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden -RunOnlyIfNetworkAvailable

Set-ScheduledTask -TaskName JarvisAgent -Action $action -Settings $settings

Write-Host "Tâche planifiée JarvisAgent mise à jour avec succès pour exécution en arrière-plan."
Write-Host "Les logs uvicorn seront redirigés vers C:\Users\Carl\Jarvis\logs\uvicorn.log"