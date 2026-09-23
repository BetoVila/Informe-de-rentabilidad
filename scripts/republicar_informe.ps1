# Republica informe.html FUERA de la nocturna (p. ej. tras un cambio de presentacion) SIN perder la capa de nomina:
# sobre el ultimo run con current.json.gz re-extrae nomina y personal (se borran al final de cada lectura por privacidad),
# prepara, construye con la clave del personal (DPAPI, nunca se imprime) y publica atomico como Actualizar.ps1.
# No toca Wialon ni Locatel ni re-triangula. Toma refresh.lock: si la nocturna esta corriendo, no hace nada.
# ANTES: instalar el codigo nuevo con deploy-dev.ps1 -SinLanzar (este script usa lo instalado, no el repo).
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\RazoRentabilidad\scripts\republicar_informe.ps1
$ErrorActionPreference='Stop'
$root='C:\ProgramData\RazoRentabilidad'
$cfg=Get-Content (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$run=(Get-ChildItem -LiteralPath (Join-Path $root 'work') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'current.json.gz') } | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
if(-not $run){ throw 'No hay run con current.json.gz' }
Write-Output "run: $run"
$py=Join-Path $root 'runtime\python\python.exe'
$node=Join-Path $root 'runtime\node\node.exe'
$ps64=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$ps32=Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
$hist=Join-Path $root 'historicos'
$hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
$mode=if($cfg.scheduled){'scheduled'}else{'pending'}   # como la nocturna: si no, el aviso de actualizacion queda incoherente
# clave por DPAPI (nunca se imprime)
Add-Type -AssemblyName System.Security
$alcance=if($cfg.clavePersonalAlcance -eq 'CurrentUser'){[Security.Cryptography.DataProtectionScope]::CurrentUser}else{[Security.Cryptography.DataProtectionScope]::LocalMachine}
$clave=[Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($cfg.clavePersonalFile),$null,$alcance))
# lock para no cruzarse con la nocturna
$lock=[IO.File]::Open((Join-Path $root 'refresh.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
try{
    # 1) nomina con detalle (fuente laboral)
    $na=@((Join-Path $root 'scripts\export_rentabilidad_nomina_v1.py'),'--root',$cfg.optional.laboral,'--output',(Join-Path $run 'nomina_v1.json'),'--from-date',$cfg.from,'--to-date',$hasta,'--output-detail',(Join-Path $run 'nomina_detalle.json'))
    & $py @na; if($LASTEXITCODE -ne 0){ throw 'Fallo nomina' }
    # 2) enlace parte-conductor (partes de Access)
    $pa=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $root 'scripts\export_rentabilidad_personal_v1.ps1'),'-Desde',$cfg.from,'-Hasta',$hasta,'-SourcePath',(Join-Path $cfg.sourceRoot 'PartesTrabajo\Partes 7.0.accdb'),'-OutputPath',(Join-Path $run 'personal_v1.json'))
    & $ps64 @pa; if($LASTEXITCODE -ne 0){ & $ps32 @pa; if($LASTEXITCODE -ne 0){ throw 'Fallo personal' } }
    # 3) preparar (regenera current.json.gz + personal_private.json; aqui se clasifican las cuentas)
    & $node (Join-Path $root 'scripts\prepare-data.mjs') $run $hist; if($LASTEXITCODE -ne 0){ throw 'Fallo prepare-data' }
    # 4) construir con la clave
    $env:RENTABILIDAD_CLAVE_PERSONAL=$clave
    try{ & $node (Join-Path $root 'scripts\build.mjs') (Join-Path $run 'current.json.gz') $run $mode $cfg.at }
    finally{ Remove-Item Env:\RENTABILIDAD_CLAVE_PERSONAL -ErrorAction SilentlyContinue }
    if($LASTEXITCODE -ne 0){ throw 'Fallo build (controles)' }
    # 5) verificar la huella y publicar atomico (Replace con respaldo con nombre: en UNC un $null falla)
    $receipt=Get-Content -LiteralPath (Join-Path $run 'verification.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $ready=Join-Path $run 'informe.html'
    if((Get-FileHash -LiteralPath $ready -Algorithm SHA256).Hash.ToLower() -ne $receipt.sha256){ throw 'Huella no coincide' }
    $target=Join-Path $cfg.publicPath 'informe.html'
    $incoming=Join-Path $cfg.publicPath ('informe.'+[guid]::NewGuid().ToString('N')+'.tmp')
    Copy-Item -LiteralPath $ready -Destination $incoming
    if(Test-Path -LiteralPath $target){ [IO.File]::Replace($incoming,$target,$target+'.anterior') } else { [IO.File]::Move($incoming,$target) }
    "PUBLICADO: $((Get-Item $target).Length) bytes  $((Get-Item $target).LastWriteTime)"
}finally{
    $lock.Dispose()
    $clave=$null
    # datos personales fuera del disco
    foreach($f in 'nomina_detalle.json','personal_v1.json','personal_private.json'){ Remove-Item -LiteralPath (Join-Path $run $f) -Force -ErrorAction SilentlyContinue }
    Get-ChildItem -LiteralPath $run -File | Where-Object { $_.Name -match '^access-(copia|personal)-[a-f0-9]{32}\.(accdb|laccdb)$' } | Remove-Item -Force -ErrorAction SilentlyContinue
}
