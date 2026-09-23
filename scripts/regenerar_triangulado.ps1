# Regenera SOLO triangulado_v2.json (demanda + triangular, con los mismos argumentos que Actualizar.ps1) usando las trazas
# ya guardadas en historicos\ (no se conecta a Wialon ni a Locatel), y lo publica atomico en _RENTABILIDAD.
# No toca informe.html ni re-extrae nada mas. Toma refresh.lock: si la nocturna esta corriendo, no hace nada.
# ANTES: instalar el codigo nuevo con deploy-dev.ps1 -SinLanzar (este script usa lo instalado, no el repo).
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\RazoRentabilidad\scripts\regenerar_triangulado.ps1
$ErrorActionPreference='Stop'
$root='C:\ProgramData\RazoRentabilidad'
$cfg=Get-Content (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$py=Join-Path $root 'runtime\python\python.exe'
$hist=Join-Path $root 'historicos'; $sroot=$cfg.sourceRoot
$hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
$lock=[IO.File]::Open((Join-Path $root 'refresh.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$run=Join-Path $env:TEMP ('triangulado_'+[guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $run | Out-Null
try{
    $demf=Join-Path $run 'demanda_triangular.json'; $trif=Join-Path $run 'triangulado_v2.json'
    "demanda $($cfg.from)..$hasta"
    & $py (Join-Path $root 'scripts\demanda_triangular_v2.py') --root (Join-Path $sroot 'Gesruta') --from-date $cfg.from --to-date $hasta --plates (Join-Path $hist 'movertis_plates.txt') --con-hormigon --con-nacional --salida $demf
    if($LASTEXITCODE -ne 0){ throw 'demanda' }
    "triangulando..."
    & $py (Join-Path $root 'scripts\triangular_v2.py') --demanda $demf --wialon (Join-Path $hist 'wialon_hist') --locatel (Join-Path $hist 'locatel_hist') --sensores (Join-Path $hist 'sensores_erp.json') --geocode (Join-Path $hist 'coords_lugares_por_casa.json') --plates (Join-Path $hist 'movertis_plates.txt') --conductores (Join-Path $hist 'conductores_hash_codigo.json') --bajas (Join-Path $sroot '_TACOGRAFO\export\bajas_flota_erp.json') --flota (Join-Path $sroot '_TACOGRAFO\export\flota_erp.json') --ancla (Join-Path $sroot '_TARIFAS\export\viajes-ancla-razo.json.gz') --salida $trif --diag (Join-Path $run 'triangulado_v2_diag.json')
    if($LASTEXITCODE -ne 0){ throw 'triangular' }
    # comprobacion rapida
    & $py -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8'))['viajes']; print('viajes',len(d),'medidos',sum(1 for v in d if v.get('medido')),'nacionales',sum(1 for v in d if v.get('nacional')))" $trif
    # publicacion atomica (Replace con respaldo con nombre, como la nocturna) + copia de reserva en cache\
    $pub=Join-Path $cfg.publicPath 'triangulado_v2.json'; $tmp=Join-Path $cfg.publicPath ('triangulado_v2.'+[guid]::NewGuid().ToString('N')+'.tmp')
    Copy-Item -LiteralPath $trif -Destination $tmp -Force
    if(Test-Path -LiteralPath $pub){ [IO.File]::Replace($tmp,$pub,$pub+'.anterior') } else { [IO.File]::Move($tmp,$pub) }
    Copy-Item -LiteralPath $trif -Destination (Join-Path $root 'cache\triangulado_v2.json') -Force
    "PUBLICADO triangulado_v2.json: $((Get-Item $pub).Length) bytes  $((Get-Item $pub).LastWriteTime)"
}finally{
    $lock.Dispose()
    Remove-Item -Recurse -Force $run -ErrorAction SilentlyContinue
}
