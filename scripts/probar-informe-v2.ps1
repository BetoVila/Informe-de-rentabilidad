# SOLO DESARROLLO: construye un informe de PRUEBA con el triangulado v2 sin tocar el publicado ni las fuentes obligatorias.
# Copia la ultima lectura buena (work\<run>), re-extrae la actividad de GesRuta con --triangulado v2, concilia y construye.
param([string]$Triangulado, [string]$Salida)
$ErrorActionPreference='Stop'
$root='C:\ProgramData\RazoRentabilidad'
$src=Split-Path $PSScriptRoot -Parent
$py=Join-Path $root 'runtime\python\python.exe'
$node=Join-Path $root 'runtime\node\node.exe'
$config=Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$ultimo=Get-ChildItem -LiteralPath (Join-Path $root 'work') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'current.json.gz') } | Sort-Object LastWriteTime | Select-Object -Last 1
if(-not $ultimo){throw 'No hay una lectura buena en work\'}
New-Item -ItemType Directory -Force -Path $Salida | Out-Null
Get-ChildItem -LiteralPath $ultimo.FullName -File | Where-Object { $_.Name -notin @('informe.html','verification.json','current.json.gz','actividad_v1.json') } | Copy-Item -Destination $Salida -Force
$hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
& $py (Join-Path $src 'scripts\export_rentabilidad_gesruta_actividad_v1.py') --root (Join-Path $config.sourceRoot 'Gesruta') --output (Join-Path $Salida 'actividad_v1.json') --from-date $config.from --to-date $hasta --lugares (Join-Path $config.publicPath 'lugares-provincias.csv') --gps (Join-Path $root 'cache\lugares_gps.json') --triangulado $Triangulado --horas (Join-Path $root 'cache\horas_vehiculo_mes.json')
if($LASTEXITCODE -ne 0){throw 'Fallo la actividad'}
& $node (Join-Path $src 'scripts\prepare-data.mjs') $Salida (Join-Path $root 'historicos')
if($LASTEXITCODE -ne 0){throw 'Fallo prepare-data'}
& $node (Join-Path $src 'scripts\build.mjs') (Join-Path $Salida 'current.json.gz') $Salida pending $config.at
if($LASTEXITCODE -ne 0){throw 'Fallo build'}
Write-Output ('Informe de prueba: '+(Join-Path $Salida 'informe.html'))
