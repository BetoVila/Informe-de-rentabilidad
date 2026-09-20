# Restaura la carpeta runtime\ (Python 3.12 y Node, ~130 MB, no va en git) desde el paquete publicado.
param([string]$Paquete='P:\_RENTABILIDAD\programa.zip')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Add-Type -AssemblyName System.IO.Compression.FileSystem
if(-not(Test-Path -LiteralPath $Paquete)){throw ('No se encuentra '+$Paquete)}
$zip=[IO.Compression.ZipFile]::OpenRead($Paquete)
try{
    $n=0
    foreach($e in $zip.Entries){
        $nombre=$e.FullName.Replace('\','/')
        if(-not $nombre.StartsWith('runtime/')-or $nombre.EndsWith('/')){continue}
        $destino=Join-Path $root ($nombre.Replace('/','\'))
        New-Item -ItemType Directory -Force -Path (Split-Path $destino -Parent) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($e,$destino,$true);$n++
    }
    Write-Output ('Runtime restaurado: '+$n+' ficheros en '+(Join-Path $root 'runtime'))
}finally{$zip.Dispose()}
