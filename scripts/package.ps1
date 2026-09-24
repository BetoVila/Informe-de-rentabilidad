param([string]$ReleaseName='release-r3')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$release=Join-Path $root $ReleaseName
New-Item -ItemType Directory -Path $release -Force | Out-Null
if((Get-Item -LiteralPath (Join-Path $root 'runtime\node\LICENSE.txt')).Length -lt 1000){throw 'Falta la licencia original de Node.js para esta version.'}
if(-not(Test-Path -LiteralPath (Join-Path $root 'vendor\LICENSES'))){throw 'Faltan las licencias de las librerias de vendor.'}
if(-not(Test-Path -LiteralPath (Join-Path $root 'vendor\python312\pyodbc.cp312-win_amd64.pyd'))){throw 'Falta pyodbc 5.3.0 para el Python 3.12 empaquetado (lector de seguros).'}
$archive=Join-Path $release 'programa.zip'
if(Test-Path -LiteralPath $archive){throw 'El paquete ya existe. Cree una release nueva; no se pisa.'}
# Los .ps1 van con BOM: Windows PowerShell 5 lee sin BOM como ANSI y estropea las tildes.
$bom=New-Object Text.UTF8Encoding($true)
foreach($f in (@(Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File)+@(Get-ChildItem -LiteralPath (Join-Path $root 'scripts') -Filter '*.ps1' -File))){
    $t=[IO.File]::ReadAllText($f.FullName,(New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText($f.FullName,$t,$bom)
}
# Nada privado ni de pruebas viaja en el paquete: solo el programa.
$items=@('src','scripts','runtime','vendor','config','Actualizar.ps1','Poner-clave-personal.ps1','Poner-sal-conductores.ps1','LEEME.txt')|ForEach-Object{Join-Path $root $_}
Compress-Archive -LiteralPath $items -DestinationPath $archive -CompressionLevel Optimal
$hash=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
[IO.File]::WriteAllText((Join-Path $release 'programa.sha256'),$hash,(New-Object Text.UTF8Encoding($false)))
Copy-Item -LiteralPath (Join-Path $root 'Instalar.ps1'),(Join-Path $root 'ACTIVAR EN SERVIDOR.cmd'),(Join-Path $root 'INSTALAR EN ESTE PC.cmd'),(Join-Path $root 'CLAVE DEL PERSONAL.cmd'),(Join-Path $root 'SAL DE CONDUCTORES.cmd'),(Join-Path $root 'LEEME.txt') -Destination $release
Write-Output ('Paquete: '+$archive)
Write-Output ('SHA256: '+$hash)
