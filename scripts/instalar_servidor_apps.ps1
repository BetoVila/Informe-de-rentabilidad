# Instala en este PC el servidor http de las apps publicadas (informe de rentabilidad, tarifas, tacógrafo, carburantes),
# para abrirlas en vivo con herramientas que no abren ficheros locales ni rutas de red (Codex). Solo lectura y solo este PC.
# Copia servir_apps.py y su lanzador a C:\ProgramData\RazoApps, registra la tarea «Razo - Apps por http» (al iniciar sesión
# y cada 5 minutos: si el servidor se cae, vuelve solo) y la arranca. No necesita permisos de administrador.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\instalar_servidor_apps.ps1
$ErrorActionPreference='Stop'
$src=Split-Path -Parent $MyInvocation.MyCommand.Path
$dst='C:\ProgramData\RazoApps'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -LiteralPath (Join-Path $src 'servir_apps.py') -Destination $dst -Force
Copy-Item -LiteralPath (Join-Path $src 'servir_apps_callado.vbs') -Destination $dst -Force
if(-not (Test-Path 'C:\ProgramData\RazoRentabilidad\runtime\python\python.exe')){throw 'Falta el Python del informe (C:\ProgramData\RazoRentabilidad\runtime\python): instala antes el informe.'}
$nombre='Razo - Apps por http'
$accion=New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"'+(Join-Path $dst 'servir_apps_callado.vbs')+'"')
$alIniciar=New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$cada5=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$ajustes=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$quien=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger @($alIniciar,$cada5) -Settings $ajustes -Principal $quien -Description 'Sirve por http, solo en este PC (http://127.0.0.1:8710/), las apps publicadas en \\SERVIDOR\Programas para abrirlas en vivo (Codex). Solo lectura. Instalado por scripts\instalar_servidor_apps.ps1 del repo del informe.' -Force | Out-Null
Start-ScheduledTask -TaskName $nombre
Start-Sleep -Seconds 3
try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:8710/estado.json' -UseBasicParsing -TimeoutSec 20;'Servidor en marcha: http://127.0.0.1:8710/ ('+$r.StatusCode+')'}catch{'El servidor aún no responde: '+$_.Exception.Message}
