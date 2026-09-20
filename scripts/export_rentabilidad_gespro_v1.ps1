# Gasoleo del DEPOSITO PROPIO de la nave (GesproWin V3, base Access) + exportaciones de texto del surtidor.
# SOLO LECTURA: el .mdb se COPIA a una carpeta de trabajo antes de abrirlo. No hay precio en estos datos, solo litros.
# Dos fuentes que se mezclan sin repetir servicios (cada uno lleva su numero de operacion); manda la base.
param(
  [string]$Desde='2025-01-01',
  [string]$Hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd'),
  [Parameter(Mandatory=$true)][string]$SourceMdb,
  [Parameter(Mandatory=$true)][string]$TextDir,
  [Parameter(Mandatory=$true)][string]$WorkDir,
  [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$inv = [Globalization.CultureInfo]::InvariantCulture
$d0 = [datetime]::ParseExact($Desde,'yyyy-MM-dd',$inv); $d1 = [datetime]::ParseExact($Hasta,'yyyy-MM-dd',$inv)
function Norm-Placa([string]$s) {
  $k = ($s -replace '[\s\-\.]','').ToUpper()
  if ($k -match '^\d{4}[A-Z]{3}$') { return $k } else { return $null }
}
function Hora4([string]$s) { $s = ($s + '').Trim(); if ($s.Length -ge 4) { return $s.Substring(0,2) + ':' + $s.Substring(2,2) } else { return '' } }

$meta = [ordered]@{ desde=$Desde; hasta=$Hasta; read_at=(Get-Date).ToString('o'); disponible=$false; aviso=$null
  fuentes=[ordered]@{ base=[ordered]@{disponible=$false;modificado=$null;maxFecha=$null;filas=0;aviso=$null}; texto=[ordered]@{disponible=$false;maxFecha=$null;filas=0;malas=0;aviso=$null} } }
$rows = New-Object System.Collections.Generic.List[object]
$vistas = @{}

# ---- Fuente A: la base de GesproWin (copia de trabajo)
$copia = Join-Path $WorkDir 'gespro_copia.mdb'
try {
  if (-not (Test-Path -LiteralPath $SourceMdb)) { throw "No se encuentra la base del surtidor: $SourceMdb" }
  New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
  $meta.fuentes.base.modificado = (Get-Item -LiteralPath $SourceMdb).LastWriteTime.ToString('o')
  Copy-Item -LiteralPath $SourceMdb -Destination $copia -Force
  $conn = $null
  foreach ($prov in 'Microsoft.ACE.OLEDB.12.0','Microsoft.ACE.OLEDB.16.0') {
    try { $c = New-Object System.Data.OleDb.OleDbConnection "Provider=$prov;Data Source=$copia;Mode=Read;Persist Security Info=False;"; $c.Open(); $conn = $c; break } catch { }
  }
  if ($null -eq $conn) { throw 'No hay proveedor Access (ACE) instalado para leer la base del surtidor.' }
  try {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = 'SELECT DataGlobal, HMOperacio, Matricula, Quilometres, Quantitat, IdMConta FROM Serveis'
    $rd = $cmd.ExecuteReader()
    while ($rd.Read()) {
      if ($rd.IsDBNull(0) -or $rd.IsDBNull(4)) { continue }
      $fe = [datetime]$rd.GetValue(0); $lit = [double]$rd.GetValue(4)
      if ($lit -le 0) { continue }
      $meta.fuentes.base.filas++
      if ($null -eq $meta.fuentes.base.maxFecha -or $fe.ToString('yyyy-MM-dd') -gt $meta.fuentes.base.maxFecha) { $meta.fuentes.base.maxFecha = $fe.ToString('yyyy-MM-dd') }
      if ($fe.Date -lt $d0 -or $fe.Date -gt $d1) { continue }
      $hm = if ($rd.IsDBNull(1)) { '' } else { [string]$rd.GetValue(1) }
      $km = $null; $kt = if ($rd.IsDBNull(3)) { '' } else { ([string]$rd.GetValue(3)).Trim() }
      if ($kt -match '^\d+$' -and [int64]$kt -gt 0) { $km = [int64]$kt }
      $pm = if ($rd.IsDBNull(2)) { '' } else { [string]$rd.GetValue(2) }
      $pl = Norm-Placa $pm
      $op = if ($rd.IsDBNull(5) -or ([string]$rd.GetValue(5)).Trim() -eq '') { $null } else { '0' + ([string]$rd.GetValue(5)).Trim() }
      $hh = Hora4 $hm
      $clave = if ($op) { 'op:' + $op } else { 'k:' + $fe.ToString('yyyy-MM-dd') + '|' + $hh + '|' + $pl + '|' + $lit.ToString($inv) }
      if ($vistas.ContainsKey($clave)) { continue }
      $vistas[$clave] = $true
      $rows.Add([ordered]@{ fecha=$fe.ToString('yyyy-MM-dd'); hora=$hh; placa=$pl; litros=[math]::Round($lit,2); km=$km; fuente='base' })
    }
    $rd.Close()
    $meta.fuentes.base.disponible = $true
  } finally { $conn.Close() }
} catch { $meta.fuentes.base.aviso = $_.Exception.Message }
finally { if (Test-Path -LiteralPath $copia) { Remove-Item -LiteralPath $copia -Force -ErrorAction SilentlyContinue } }

# ---- Fuente B: exportaciones de texto (operacion;punto;AAAAMMDD;HHMM;matricula;000;litros)
try {
  if (-not (Test-Path -LiteralPath $TextDir)) { throw "No se encuentra la carpeta de exportaciones: $TextDir" }
  $enc = [Text.Encoding]::GetEncoding(1252)
  foreach ($f in Get-ChildItem -LiteralPath $TextDir -Filter *.txt -File) {
    foreach ($linea in [IO.File]::ReadAllLines($f.FullName, $enc)) {
      $t = $linea.Trim(); if ($t -eq '') { continue }
      $p = $t.Split(';')
      if ($p.Count -lt 7 -or $p[2] -notmatch '^\d{8}$') { $meta.fuentes.texto.malas++; continue }
      try { $fe = [datetime]::ParseExact($p[2],'yyyyMMdd',$inv); $lit = [double]::Parse($p[6],$inv) } catch { $meta.fuentes.texto.malas++; continue }
      if ($lit -le 0) { continue }
      $meta.fuentes.texto.filas++
      if ($null -eq $meta.fuentes.texto.maxFecha -or $fe.ToString('yyyy-MM-dd') -gt $meta.fuentes.texto.maxFecha) { $meta.fuentes.texto.maxFecha = $fe.ToString('yyyy-MM-dd') }
      if ($fe.Date -lt $d0 -or $fe.Date -gt $d1) { continue }
      $op = $p[0].Trim(); $hh = Hora4 $p[3]; $pl = Norm-Placa $p[4]
      $clave = if ($op) { 'op:' + $op } else { 'k:' + $fe.ToString('yyyy-MM-dd') + '|' + $hh + '|' + $pl + '|' + $lit.ToString($inv) }
      if ($vistas.ContainsKey($clave)) { continue }
      $vistas[$clave] = $true
      $rows.Add([ordered]@{ fecha=$fe.ToString('yyyy-MM-dd'); hora=$hh; placa=$pl; litros=[math]::Round($lit,2); km=$null; fuente='texto' })
    }
  }
  $meta.fuentes.texto.disponible = $true
} catch { $meta.fuentes.texto.aviso = $_.Exception.Message }

$meta.disponible = ($meta.fuentes.base.disponible -or $meta.fuentes.texto.disponible)
if (-not $meta.disponible) { $meta.aviso = 'Ninguna de las dos fuentes del surtidor esta disponible.' }
$ordenadas = @($rows | Sort-Object { $_.fecha }, { $_.hora })
$out = [ordered]@{ metadata=$meta; rows=$ordenadas }
[IO.File]::WriteAllText($OutputPath, (ConvertTo-Json -InputObject $out -Depth 8 -Compress), (New-Object Text.UTF8Encoding($false)))
Write-Output ("Surtidor: filas=$($ordenadas.Count); base=$($meta.fuentes.base.filas) (hasta $($meta.fuentes.base.maxFecha)); texto=$($meta.fuentes.texto.filas) (hasta $($meta.fuentes.texto.maxFecha)); Output=$OutputPath")
