# Enlace parte -> conductor y ficha de trabajo de cada empleado (Access, solo lectura).
# DATOS PERSONALES (nombre, sueldo pactado): este JSON vive SOLO en la carpeta privada de trabajo y solo alimenta la
# capa CIFRADA del informe. No se lee ni se vuelca DNI, IBAN, direccion, telefono, email, afiliacion ni fotos.
param(
  [string]$Desde='2025-01-01',
  [string]$Hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd'),
  [Parameter(Mandatory=$true)][string]$SourcePath,
  [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$inv = [Globalization.CultureInfo]::InvariantCulture
# Access es un documento VIVO (se usa a diario): se COPIA y se lee la COPIA (foto estable). Nunca se abre el que usa la gente.
$copy = Join-Path (Split-Path -Parent $OutputPath) ('access-personal-'+[guid]::NewGuid().ToString('N')+'.accdb')
Copy-Item -LiteralPath $SourcePath -Destination $copy -Force
$conn = $null
foreach ($prov in 'Microsoft.ACE.OLEDB.12.0','Microsoft.ACE.OLEDB.16.0') {
  try { $c = New-Object System.Data.OleDb.OleDbConnection "Provider=$prov;Data Source=$copy;Mode=Read;Persist Security Info=False;"; $c.Open(); $conn = $c; break } catch { }
}
if ($null -eq $conn) { Remove-Item -LiteralPath $copy -Force -ErrorAction SilentlyContinue; throw 'No hay proveedor Access (ACE) instalado.' }
$ntilde = [char]0xF1
function Fecha-Nula($v) { if ($v -is [System.DBNull] -or $null -eq $v) { return $null } else { return ([datetime]$v).ToString('yyyy-MM-dd') } }
function Num-Nulo($v) { if ($v -is [System.DBNull] -or $null -eq $v) { return $null } else { return [double]$v } }
try {
  $start = ([datetime]$Desde).ToString('MM/dd/yyyy'); $endEx = ([datetime]$Hasta).AddDays(1).ToString('MM/dd/yyyy')
  # ---- partes: solo id del parte y id del responsable (numerico, no identifica por si solo)
  $cmd = $conn.CreateCommand(); $cmd.CommandText = "SELECT IdParteTrabajo, IdResponsable FROM PartesTrabajo WHERE Fecha >= #$start# AND Fecha < #$endEx#"
  $rd = $cmd.ExecuteReader(); $parts = New-Object System.Collections.Generic.List[object]
  while ($rd.Read()) {
    $emp = $null; if (-not $rd.IsDBNull(1)) { $emp = [int]$rd.GetValue(1); if ($emp -eq 0) { $emp = $null } }
    $parts.Add([ordered]@{ id=[int]$rd.GetValue(0); emp=$emp })
  }
  $rd.Close()
  # ---- empleados: consulta guardada con el ultimo contrato de cada persona; SOLO estas columnas
  $sql = "SELECT IdResponsable, [Apellidos y Nombre], Empresa, Hormigonera, [Ba${ntilde}era], Nacional, Taller, Administracion, CosteHoraOrdinaria, CosteHoraExtraordinaria, SueldoMensualPactado, CosteMensualEstimado, Vigente, FechaInicioContrato, FechaFinContrato FROM UltimoContratoVigentePorEmpleado"
  $cmd = $conn.CreateCommand(); $cmd.CommandText = $sql
  $rd = $cmd.ExecuteReader(); $emps = New-Object System.Collections.Generic.List[object]
  while ($rd.Read()) {
    $emps.Add([ordered]@{
      id=[int]$rd.GetValue(0); nombre=$(if ($rd.IsDBNull(1)) { '' } else { ([string]$rd.GetValue(1)).Trim() }); empresa=$(if ($rd.IsDBNull(2)) { '' } else { [string]$rd.GetValue(2) })
      tipo=[ordered]@{ hormigonera=[bool]$(if ($rd.IsDBNull(3)) { $false } else { $rd.GetValue(3) }); banera=[bool]$(if ($rd.IsDBNull(4)) { $false } else { $rd.GetValue(4) });
                       nacional=[bool]$(if ($rd.IsDBNull(5)) { $false } else { $rd.GetValue(5) }); taller=[bool]$(if ($rd.IsDBNull(6)) { $false } else { $rd.GetValue(6) });
                       administracion=[bool]$(if ($rd.IsDBNull(7)) { $false } else { $rd.GetValue(7) }) }
      costeHoraOrd=(Num-Nulo $rd.GetValue(8)); costeHoraExtra=(Num-Nulo $rd.GetValue(9)); sueldoPactado=(Num-Nulo $rd.GetValue(10)); costeMensualEstimado=(Num-Nulo $rd.GetValue(11))
      vigente=[bool]$(if ($rd.IsDBNull(12)) { $false } else { $rd.GetValue(12) }); inicio=(Fecha-Nula $rd.GetValue(13)); fin=(Fecha-Nula $rd.GetValue(14))
    })
  }
  $rd.Close()
  $out = [ordered]@{ metadata=[ordered]@{ desde=$Desde; hasta=$Hasta; read_at=(Get-Date).ToString('o'); aviso='DATOS PERSONALES: solo capa cifrada' }; parts=$parts.ToArray(); employees=$emps.ToArray() }
  [IO.File]::WriteAllText($OutputPath, (ConvertTo-Json -InputObject $out -Depth 8 -Compress), (New-Object Text.UTF8Encoding($false)))
  $conResp = @($parts | Where-Object { $_.emp }).Count
  $ids = @{}; foreach ($e in $emps) { $ids[$e.id] = $true }
  $enLista = @($parts | Where-Object { $_.emp -and $ids.ContainsKey($_.emp) }).Count
  Write-Output ("Personal: partes=$($parts.Count); con responsable=$conResp; responsables que existen en la lista de empleados=$enLista; empleados=$($emps.Count); vigentes=" + @($emps | Where-Object { $_.vigente }).Count + "; Output=$OutputPath")
} finally { if ($conn) { $conn.Close() }; Remove-Item -LiteralPath $copy -Force -ErrorAction SilentlyContinue }
