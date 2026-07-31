# Instala watchdog como tarefa agendada do Windows (login do usuario)
param(
    [string]$TaskName = "LauraWatchdog",
    [string]$ScriptPath = ""
)

if (-not $ScriptPath) {
    $ScriptPath = Join-Path $PSScriptRoot "laura_watchdog.py"
}

$Action = New-ScheduledTaskAction -Execute "pythonw.exe" -Argument "`"$ScriptPath`"" -WorkingDirectory (Split-Path $PSScriptRoot -Parent)
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force

Write-Host "Watchdog instalado como tarefa '$TaskName' (executa no login de $env:USERNAME)"
Write-Host "Script: $ScriptPath"
Write-Host ""
Write-Host "Comandos:"
Write-Host "  Iniciar agora: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Parar:         Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Status:        Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Remover:       Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
