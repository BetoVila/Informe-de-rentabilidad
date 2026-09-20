param([switch]$SinLanzar)
# SOLO PARA DESARROLLO (no va en el paquete): copia el programa de trabajo a la carpeta instalada y lanza la tarea.
$ErrorActionPreference='Stop'
$r=$PSScriptRoot;$pp='C:\ProgramData\RazoRentabilidad'
try{$l=[IO.File]::Open((Join-Path $pp 'refresh.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$l.Dispose()}catch{throw 'Hay una lectura en curso.'}
$bom=New-Object Text.UTF8Encoding($true)
foreach($f in (@(Get-ChildItem -LiteralPath $r -Filter '*.ps1' -File)+@(Get-ChildItem -LiteralPath (Join-Path $r 'scripts') -Filter '*.ps1' -File))){
    $t=[IO.File]::ReadAllText($f.FullName,(New-Object Text.UTF8Encoding($false)));[IO.File]::WriteAllText($f.FullName,$t,$bom)
}
foreach($d in 'src','scripts','vendor','config'){& robocopy.exe (Join-Path $r $d) (Join-Path $pp $d) /MIR /NFL /NDL /NJH /NJS /NP | Out-Null;if($LASTEXITCODE -ge 8){throw ('robocopy '+$d+' fallo '+$LASTEXITCODE)}}
Copy-Item -LiteralPath (Join-Path $r 'Actualizar.ps1'),(Join-Path $r 'Poner-clave-personal.ps1'),(Join-Path $r 'LEEME.txt') -Destination $pp -Force
Write-Output 'Programa copiado a la carpeta instalada.'
if(-not $SinLanzar){Start-ScheduledTask -TaskName 'Razo-Rentabilidad-Nocturna';Write-Output 'Tarea lanzada.'}
