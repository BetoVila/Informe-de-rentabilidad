param([string]$At='03:00',[ValidateSet('Auto','Servidor','Pc')][string]$Modo='Auto')
# Instalador unico. Sirve para instalar Y para actualizar el programa: si ya existe, solo cambia los ficheros del
# programa y conserva la configuracion, los registros y la tarea. Nunca toca los sistemas de origen.
#   Modo Servidor: dentro de SERVIDOR, como administrador. Tarea SYSTEM, rutas locales de los recursos compartidos.
#   Modo Pc:       en el PC de Roberto (donde estan las claves de Movertis y Locatel). Tarea con su usuario, rutas \\SERVIDOR\...
$ErrorActionPreference='Stop'
try{
    if($At -notmatch '^([01]\d|2[0-3]):[0-5]\d$'){throw 'Hora incorrecta. Use HH:mm.'}
    if($Modo -eq 'Auto'){$Modo=if($env:COMPUTERNAME -eq 'SERVIDOR'){'Servidor'}else{'Pc'}}
    $taskName='Razo-Rentabilidad-Nocturna'
    $private='C:\ProgramData\RazoRentabilidad'
    $utf8=New-Object System.Text.UTF8Encoding($false)
    if($Modo -eq 'Servidor'){
        if($env:COMPUTERNAME -ne 'SERVIDOR'){throw 'El modo Servidor solo se ejecuta DENTRO de SERVIDOR.'}
        $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Abra PowerShell como administrador en SERVIDOR y ejecute este instalador.'}
        $programas=[IO.Path]::GetFullPath((Get-SmbShare -Name Programas).Path)
        $documentos=[IO.Path]::GetFullPath((Get-SmbShare -Name Documentos).Path)
    }else{
        if($env:COMPUTERNAME -eq 'SERVIDOR'){throw 'En SERVIDOR se instala en modo Servidor.'}
        $programas='\\SERVIDOR\Programas'
        $documentos='\\SERVIDOR\Documentos'
    }
    foreach($p in @('PartesTrabajo\Partes 7.0.accdb','Gesruta\EMPTR21','Gesruta\EMPAG21')){if(-not(Test-Path -LiteralPath (Join-Path $programas $p))){throw ('No se encuentra el origen: '+$p)}}
    $public=Join-Path $programas '_RENTABILIDAD'
    $archive=Join-Path $PSScriptRoot 'programa.zip'
    if(-not(Test-Path -LiteralPath $archive)){throw 'Falta programa.zip junto al instalador.'}
    $expected=(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'programa.sha256') -Raw).Trim()
    if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected){throw 'La huella del paquete no coincide. No se instala.'}
    $existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $upgrade=Test-Path -LiteralPath (Join-Path $private 'Actualizar.ps1')
    New-Item -ItemType Directory -Path $private -Force | Out-Null
    if($upgrade){
        # No se cambian ficheros a media lectura.
        try{$l=[IO.File]::Open((Join-Path $private 'refresh.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$l.Dispose()}catch{throw 'Hay una lectura en curso. Repita el instalador en unos minutos.'}
    }
    if($Modo -eq 'Servidor'){
        # El motor SYSTEM nunca se ejecuta desde una carpeta modificable por todos.
        & icacls.exe $private /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    }else{
        & icacls.exe $private /inheritance:r /grant:r ($env:USERDOMAIN+'\'+$env:USERNAME+':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    }
    if($LASTEXITCODE -ne 0){throw 'No se pudieron proteger los archivos del programa.'}
    Expand-Archive -LiteralPath $archive -DestinationPath $private -Force
    New-Item -ItemType Directory -Path $public -Force | Out-Null
    # Configuracion: se conserva la existente; solo se completan las rutas.
    $configPath=Join-Path $private 'config.json'
    $config=[ordered]@{sourceRoot=$programas;publicPath=$public;from='2025-01-01';at=$At;scheduled=$false;optional=[ordered]@{}}
    if(Test-Path -LiteralPath $configPath){
        $prev=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if($prev.from){$config.from=$prev.from}
        if($prev.at -and -not $PSBoundParameters.ContainsKey('At')){$config.at=$prev.at}
        $config.scheduled=[bool]$prev.scheduled
        if($prev.clavePersonalFile){$config.clavePersonalFile=$prev.clavePersonalFile}
    }
    foreach($o in @(@('laboral',(Join-Path $documentos 'LABORAL\_NOMINAS')),@('gasoil',(Join-Path $documentos 'Z Datos Gasoil')),@('buzon',(Join-Path $documentos 'A CARBURANTES')),@('repostajes',(Join-Path $programas 'Analizador Carburantes\datos\repostajes')),@('gespromdb',(Join-Path $programas 'Analizador Carburantes\datos\gespro\GesproWinBD.mdb')))){
        if(Test-Path -LiteralPath $o[1]){$config.optional[$o[0]]=$o[1]}else{Write-Output ('Aviso: no se encuentra '+$o[1]+'; esa fuente opcional quedara sin leer.')}
    }
    # Contabilidad real: la trae el ERP a su base en Docker (solo en el PC de Roberto).
    if($Modo -eq 'Pc' -and (Get-Command docker -ErrorAction SilentlyContinue)){$config.optional['contabilidad']=$true;$config.optional['movertis']=$true}
    [IO.File]::WriteAllText($configPath,($config|ConvertTo-Json -Depth 5),$utf8)
    $ps=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Write-Output 'Lectura completa y controles. Puede tardar un minuto.'
    & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $private 'Actualizar.ps1')
    if($LASTEXITCODE -ne 0){
        if(-not $existing){throw 'La primera lectura no paso los controles. NO se ha registrado la tarea. Revise los registros de la carpeta privada.'}
        Write-Output 'AVISO: la lectura de prueba no paso los controles; se conserva el informe anterior y la tarea existente.'
    }
    if($Modo -eq 'Pc'){
        # Ejecucion sin ventana, como el resto de tareas de la casa.
        $vbs="Set sh=CreateObject(""WScript.Shell"")`r`nsh.CurrentDirectory=""$private""`r`nrc=sh.Run(""powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """"$private\Actualizar.ps1"""""",0,True)`r`nWScript.Quit rc`r`n"
        [IO.File]::WriteAllText((Join-Path $private 'Actualizar-callado.vbs'),$vbs,[Text.Encoding]::ASCII)
        $ahora="Set sh=CreateObject(""WScript.Shell"")`r`nsh.Run ""schtasks.exe /Run /TN $taskName"",0,True`r`nsh.Popup ""Actualizando el informe de rentabilidad. Tarda menos de un minuto; despues pulse F5 en el informe."",6,""Rentabilidad"",64`r`n"
        [IO.File]::WriteAllText((Join-Path $private 'Actualizar-ahora.vbs'),$ahora,[Text.Encoding]::ASCII)
        $action=New-ScheduledTaskAction -Execute (Join-Path $env:WINDIR 'System32\wscript.exe') -Argument ('//B //Nologo "'+$private+'\Actualizar-callado.vbs"') -WorkingDirectory $private
        $identity=New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN+'\'+$env:USERNAME) -LogonType Interactive -RunLevel Limited
        $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    }else{
        $action=New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$private+'\Actualizar.ps1"') -WorkingDirectory $private
        $identity=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    }
    if(-not $existing -or $PSBoundParameters.ContainsKey('At')){
        $trigger=New-ScheduledTaskTrigger -Daily -At $config.at
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $identity -Force -Description 'Informe privado de rentabilidad (GesRuta, Access, Solred, surtidor, nomina). Lectura sola, controles antes de publicar y ultimo corte valido si falla.' | Out-Null
    }
    $config.scheduled=$true
    [IO.File]::WriteAllText($configPath,($config|ConvertTo-Json -Depth 5),$utf8)
    Start-ScheduledTask -TaskName $taskName
    Write-Output ('Modo '+$Modo+': tarea '+$taskName+' registrada y lectura lanzada. Compruebe estado.html hasta que indique Lectura completada.')
    Write-Output ('Horario: '+$config.at+' (hora de '+$env:COMPUTERNAME+'). Proxima ejecucion: '+(Get-ScheduledTaskInfo -TaskName $taskName).NextRunTime)
}catch{
    Write-Output ('NO INSTALADO: '+$_.Exception.Message)
    exit 1
}
