# setup_tarea_backup.ps1
# Registra una Tarea Programada de Windows que ejecuta backup.py cada dia a las 3:00 AM.
# EJECUTAR UNA SOLA VEZ como Administrador:
#   Right-click en este archivo → "Ejecutar con PowerShell" (como administrador)

$ErrorActionPreference = "Stop"

# Ruta al python y al script (ajusta si Python esta en otra ubicacion)
$python  = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = "python" }

$script  = Join-Path $PSScriptRoot "backup.py"
$logdir  = Join-Path $PSScriptRoot "backups"

if (-not (Test-Path $logdir)) { New-Item -ItemType Directory -Path $logdir | Out-Null }

$taskName   = "CRM_Andamios_Backup_Diario"
$action     = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`"" `
    -WorkingDirectory $PSScriptRoot

$trigger    = New-ScheduledTaskTrigger -Daily -At "03:00AM"

$settings   = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal  = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Eliminar si ya existia
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Tarea anterior eliminada."
}

Register-ScheduledTask `
    -TaskName  $taskName `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Description "Respaldo diario automatico de la base de datos del CRM Andamios" | Out-Null

Write-Host ""
Write-Host "✓ Tarea programada registrada: '$taskName'"
Write-Host "  Ejecuta backup.py todos los dias a las 3:00 AM"
Write-Host "  Respaldos guardados en: $logdir"
Write-Host ""
Write-Host "Para verificarla: Buscador de Windows → 'Programador de tareas' → Biblioteca"
Write-Host "Para ejecutarla ahora: python `"$script`""
