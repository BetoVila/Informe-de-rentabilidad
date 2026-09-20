param([string]$Desde='2025-01-01',[string]$Hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd'),[Parameter(Mandatory=$true)][string]$SourcePath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$conn = New-Object System.Data.OleDb.OleDbConnection "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$sourcePath;Mode=Read;Persist Security Info=False;"
$before = (Get-Item -LiteralPath $sourcePath).LastWriteTimeUtc.ToString('o')
$conn.Open()
function Read-Rows([string]$sql) {
  $cmd = $conn.CreateCommand(); $cmd.CommandText = $sql
  $reader = $cmd.ExecuteReader()
  $rows = New-Object System.Collections.Generic.List[object]
  while ($reader.Read()) {
    $row = [ordered]@{}
    for($i=0;$i -lt $reader.FieldCount;$i++) {
      $value = $reader.GetValue($i)
      if($value -is [System.DBNull]) { $value = $null }
      elseif($value -is [datetime]) { $value = $value.ToString('yyyy-MM-ddTHH:mm:ss') }
      $row[$reader.GetName($i)] = $value
    }
    $rows.Add([pscustomobject]$row)
  }
  $reader.Close()
  return ,$rows.ToArray()
}
try {
  $tables = $conn.GetSchema('Tables').Rows
  $machineTable = ($tables | Where-Object {$_.TABLE_NAME -match '^M.quinas$'}).TABLE_NAME
  $categoryTable = ($tables | Where-Object {$_.TABLE_NAME -match '^Categor.as$'}).TABLE_NAME
  $cmd = $conn.CreateCommand(); $cmd.CommandText = 'SELECT TOP 1 * FROM PartesTrabajo'
  $reader = $cmd.ExecuteReader()
  $partsFields = @($reader.GetSchemaTable().Rows | Where-Object { $_.ColumnName -notmatch '^(Observaciones|Usuario|FechayHora|GasoilEstacionServicio|IdResponsable|actualiza)' } | ForEach-Object { '['+$_.ColumnName+']' })
  $reader.Close()
  $start = ([datetime]$Desde).ToString('MM/dd/yyyy')
  $endExclusive = ([datetime]$Hasta).AddDays(1).ToString('MM/dd/yyyy')
  $partQuery = "SELECT $($partsFields -join ',') FROM PartesTrabajo WHERE Fecha >= #$start# AND Fecha < #$endExclusive# ORDER BY Fecha,IdParteTrabajo"
  $parts = Read-Rows $partQuery
  $a = [char]0xE1; $ii = [char]0xED
  $machines = Read-Rows "SELECT [IdM$($a)quina] AS id, [Matr$($ii)cula] AS matricula, Titular AS titular, [IdCategor$($ii)a] AS categoria, IdActividad AS actividad FROM [$machineTable]"
  $categories = Read-Rows "SELECT [IdCategor$($ii)a] AS id,[NombreCategor$($ii)a] AS nombre FROM [$categoryTable]"
  $companies = Read-Rows 'SELECT IdEmpresa AS id,[Nombre Empresa] AS nombre,CosteEstructura AS porcentaje FROM Empresas'
  $clients = Read-Rows 'SELECT IdCliente AS id,NombreCliente AS nombre FROM Clientes'
  $plants = Read-Rows 'SELECT [IdCliente/Planta] AS id,NombrePlanta AS nombre,IdCliente AS cliente FROM PlantasHormigon'
  # Solo id y nombre de la estacion: la tabla trae usuario y clave del portal de cada estacion y NO se leen.
  $stations = Read-Rows 'SELECT IdEstacionServicio AS id, NombreEstacion AS nombre FROM EstacionServicio'
  $controls = Read-Rows "SELECT Count(*) AS partes, Sum(TotalCostesDirectos) AS directo, Sum(CosteEstructura) AS estructura, Sum(FacturacionDiariaTotal) AS ingreso, Sum(KmRecorridos) AS km FROM PartesTrabajo WHERE Fecha >= #$start# AND Fecha < #$endExclusive#"
  $after = (Get-Item -LiteralPath $sourcePath).LastWriteTimeUtc.ToString('o')
  if($before -ne $after) { throw 'Access cambio durante la lectura; repita la extraccion.' }
  $out = [ordered]@{metadata=@{source=$sourcePath;read_at=(Get-Date).ToString('o');modified=$after;desde=$Desde;hasta=$Hasta;query=$partQuery};controls=$controls;parts=$parts;machines=$machines;categories=$categories;companies=$companies;clients=$clients;plants=$plants;stations=$stations}
  $json = ConvertTo-Json -InputObject $out -Depth 8 -Compress
  [System.IO.File]::WriteAllText($outputPath,$json,(New-Object System.Text.UTF8Encoding($false)))
  Write-Output "Partes=$($parts.Count); Maquinas=$($machines.Count); Output=$outputPath"
} finally { $conn.Close() }
