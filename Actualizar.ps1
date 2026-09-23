param([string]$ConfigPath=(Join-Path $PSScriptRoot 'config.json'),[switch]$SimulateFailure)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'scripts\status.ps1')
$config=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$root=$PSScriptRoot
$workRoot=Join-Path $root 'work'
$logRoot=Join-Path $root 'logs'
New-Item -ItemType Directory -Path $workRoot,$logRoot -Force | Out-Null
# Dos ejecuciones a la vez podian publicar cortes cruzados. La exclusión cubre extracción, controles y sustitución.
try{$lock=[IO.File]::Open((Join-Path $root 'refresh.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}catch{Write-Output 'Ya hay una actualizacion en curso.';exit 0}
$run=Join-Path $workRoot ((Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
$last='';$dataTo=''
$statePath=Join-Path $config.publicPath 'estado.json'
if(Test-Path -LiteralPath $statePath){$old=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8|ConvertFrom-Json;$last=$old.lastSuccess;$dataTo=$old.dataTo}
$log=Join-Path $logRoot ((Split-Path $run -Leaf)+'.log')
Start-Transcript -LiteralPath $log | Out-Null
$code=0
try{
    $script:avisos=@()
    Write-RentabilidadStatus -PublicPath $config.publicPath -State running -Message 'Lectura y validacion en curso. El informe anterior sigue disponible.' -LastSuccess $last -DataTo $dataTo -At $config.at -RunHost $env:COMPUTERNAME -Sources $(if($old.sources){$old.sources}else{'GesRuta + Access'})
    if($SimulateFailure){throw 'Prueba controlada de fallo: no se han consultado ni modificado las fuentes.'}
    $hasta=(Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
    $ps64=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $ps32=Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
    $py=Join-Path $root 'runtime\python\python.exe'
    $node=Join-Path $root 'runtime\node\node.exe'
    $opt=$config.optional
    # ---- Fuentes que MANDAN: sin ellas no hay informe.
    $accessOut=Join-Path $run 'rentabilidad_access_v3.json'
    $argsAccess=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $root 'scripts\export_rentabilidad_access_v3.ps1'),'-Desde',$config.from,'-Hasta',$hasta,'-SourcePath',(Join-Path $config.sourceRoot 'PartesTrabajo\Partes 7.0.accdb'),'-OutputPath',$accessOut)
    & $ps64 @argsAccess
    if($LASTEXITCODE -ne 0){
        Write-Output 'Se comprueba también el proveedor Access de 32 bits.'
        & $ps32 @argsAccess
        if($LASTEXITCODE -ne 0){throw 'No se pudo extraer Access con su proveedor instalado. Revise el registro privado.'}
    }
    & $py (Join-Path $root 'scripts\export_rentabilidad_gesruta_v3.py') --root (Join-Path $config.sourceRoot 'Gesruta') --output (Join-Path $run 'rentabilidad_gesruta_v3.json') --from-date $config.from --to-date $hasta
    if($LASTEXITCODE -ne 0){throw 'Fallo de lectura de GesRuta. No se publica un corte parcial.'}
    # ---- Fuentes OPCIONALES: si una falla, el informe sale igual y lo dice. Nunca se sustituye un dato por un cero.
    function Invoke-Opcional([string]$nombre,[scriptblock]$bloque){
        try{$global:LASTEXITCODE=0;& $bloque;if($LASTEXITCODE -ne 0){throw ('salida '+$LASTEXITCODE)};Write-Output ('OK: '+$nombre)}
        catch{$script:avisos+=$nombre;Write-Output ('AVISO: '+$nombre+' no disponible ('+$_.Exception.Message+'). El informe sigue sin esta fuente.')}
    }
    # La clave del apartado de personal: la guarda el instalador cifrada para esta máquina (DPAPI). Sin clave no se lee
    # NI SE EXTRAE ningún dato personal.
    $clave=$null
    if($config.clavePersonalFile -and (Test-Path -LiteralPath $config.clavePersonalFile)){
        Add-Type -AssemblyName System.Security
        $alcance=if($config.clavePersonalAlcance -eq 'CurrentUser'){[Security.Cryptography.DataProtectionScope]::CurrentUser}else{[Security.Cryptography.DataProtectionScope]::LocalMachine}
    $clave=[Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($config.clavePersonalFile),$null,$alcance))
    }elseif($env:RENTABILIDAD_CLAVE_PERSONAL){$clave=$env:RENTABILIDAD_CLAVE_PERSONAL}
    if($opt.repostajes){Invoke-Opcional 'Solred' {& $py (Join-Path $root 'scripts\export_rentabilidad_solred_v2.py') --roots $opt.repostajes --output (Join-Path $run 'solred_v2.json') --from-date $config.from --to-date $hasta}}
    if($opt.gespromdb){Invoke-Opcional 'Surtidor de la nave' {
        $ga=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $root 'scripts\export_rentabilidad_gespro_v1.ps1'),'-Desde',$config.from,'-Hasta',$hasta,'-SourceMdb',$opt.gespromdb,'-TextDir',$opt.gasoil,'-WorkDir',$run,'-OutputPath',(Join-Path $run 'gespro_v1.json'))
        & $ps64 @ga
        if($LASTEXITCODE -ne 0){& $ps32 @ga}}}
    if($opt.laboral){Invoke-Opcional 'Nómina' {
        $na=@((Join-Path $root 'scripts\export_rentabilidad_nomina_v1.py'),'--root',$opt.laboral,'--output',(Join-Path $run 'nomina_v1.json'),'--from-date',$config.from,'--to-date',$hasta)
        if($clave){$na+=@('--output-detail',(Join-Path $run 'nomina_detalle.json'))}
        & $py @na}}
    # Informe «Vehiculos» de Mi Solred (Excel) en el buzon de carburantes: resumen por matricula para las cuentas sin ficheros mensuales.
    if($opt.buzon){Invoke-Opcional 'Solred (vehiculos)' {& $py (Join-Path $root 'scripts\export_rentabilidad_solred_vehiculos_v1.py') --roots $opt.buzon --output (Join-Path $run 'solred_vehiculos_v1.json')}}
    # La contabilidad ya la trae el ERP a su base cada noche; aqui solo se le pregunta por los totales (SELECT agregado).
    if($opt.contabilidad){Invoke-Opcional 'Contabilidad' {& $py (Join-Path $root 'scripts\export_rentabilidad_contabilidad_v1.py') --output (Join-Path $run 'contabilidad_v1.json') --from-date $config.from --to-date $hasta}}
    # Km y litros medidos por Movertis: se leen del ERP (que ya los baja y valida); aqui no se abre sesion en Movertis.
    if($opt.movertis){Invoke-Opcional 'Movertis' {& $py (Join-Path $root 'scripts\export_rentabilidad_movertis_v1.py') --output (Join-Path $run 'movertis_v1.json') --from-date $config.from --to-date $hasta}}
    # Locatel: el ERP NO lo carga en su base, pero su agente lo baja en este PC a copias\locatel_stage\locatel.json.
    # Se leen de ahi los km por matricula y dia (sin conectarse a Locatel) y se acumulan en una cache propia, que sobrevive
    # a las lecturas (el fichero del agente solo cubre ~2 semanas).
    if($opt.locatel){Invoke-Opcional 'Locatel' {& $py (Join-Path $root 'scripts\export_rentabilidad_locatel_v2.py') --cache (Join-Path $root 'cache\locatel_km_dia.json') --output (Join-Path $run 'locatel_v1.json') --from-date $config.from --to-date $hasta}}
    # Triangulado v2: cada viaje real de aridos/nacional <-> la traza del localizador y el tacografo (hora real de inicio y fin,
    # conductor, minutos de conduccion/espera, fecha real de servicio). Lee las trazas asentadas en historicos\ (se bajan aparte,
    # poco a poco). Opcional: si falla, el informe sigue con el ultimo triangulado de cache (v2 anterior, o v1).
    $hist=Join-Path $root 'historicos'
    $tri2=Join-Path $root 'cache\triangulado_v2.json'
    Invoke-Opcional 'Triangulado v2' {
        & $py (Join-Path $root 'scripts\demanda_triangular_v2.py') --root (Join-Path $config.sourceRoot 'Gesruta') --from-date $config.from --to-date $hasta --plates (Join-Path $hist 'movertis_plates.txt') --con-hormigon --salida (Join-Path $run 'demanda_triangular.json')
        if($LASTEXITCODE -ne 0){throw 'demanda'}
        & $py (Join-Path $root 'scripts\triangular_v2.py') --demanda (Join-Path $run 'demanda_triangular.json') --wialon (Join-Path $hist 'wialon_hist') --locatel (Join-Path $hist 'locatel_hist') --sensores (Join-Path $hist 'sensores_erp.json') --geocode (Join-Path $hist 'coords_lugares_por_casa.json') --plates (Join-Path $hist 'movertis_plates.txt') --conductores (Join-Path $hist 'conductores_hash_codigo.json') --bajas (Join-Path $config.sourceRoot '_TACOGRAFO\export\bajas_flota_erp.json') --flota (Join-Path $config.sourceRoot '_TACOGRAFO\export\flota_erp.json') --ancla (Join-Path $config.sourceRoot '_TARIFAS\export\viajes-ancla-razo.json.gz') --salida (Join-Path $run 'triangulado_v2.json') --diag (Join-Path $run 'triangulado_v2_diag.json')
        if($LASTEXITCODE -ne 0){throw 'triangular'}
        Copy-Item -LiteralPath (Join-Path $run 'triangulado_v2.json') -Destination $tri2 -Force
        # Publicacion en P: (esquema aditivo acordado con el ERP y tarifas): sustitucion atomica, nunca se trunca el vigente.
        # (Replace con respaldo con nombre, como el informe: en la unidad de red Replace con $null falla si el fichero ya existe.)
        $pub=Join-Path $config.publicPath 'triangulado_v2.json';$tmp=Join-Path $config.publicPath ('triangulado_v2.'+[guid]::NewGuid().ToString('N')+'.tmp')
        Copy-Item -LiteralPath (Join-Path $run 'triangulado_v2.json') -Destination $tmp -Force
        if(Test-Path -LiteralPath $pub){[IO.File]::Replace($tmp,$pub,$pub+'.anterior')}else{[IO.File]::Move($tmp,$pub)}
        # El dia de cada camion en el mapa (compacto), junto al informe: dias\<MATRICULA>_<fecha>.html ("ver dia" en Por cliente).
        & $py (Join-Path $root 'scripts\ver_dia_mapa.py') --v2 (Join-Path $run 'triangulado_v2.json') --diag (Join-Path $run 'triangulado_v2_diag.json') --wialon (Join-Path $hist 'wialon_hist') --locatel (Join-Path $hist 'locatel_hist') --geocode (Join-Path $hist 'coords_lugares_por_casa.json') --todos --salida-dir (Join-Path $config.publicPath 'dias')
        if($LASTEXITCODE -ne 0){throw 'mapas de dias'}
    }
    $triArg=if(Test-Path -LiteralPath $tri2){$tri2}else{Join-Path $root 'cache\triangulado_v1.json'}
    # Actividad operativa de GesRuta: viajes reales (albaran de cantera), km, m3/t por viaje. Opcional (si falla, sigue sin la pestana).
    Invoke-Opcional 'Actividad GesRuta' {& $py (Join-Path $root 'scripts\export_rentabilidad_gesruta_actividad_v1.py') --root (Join-Path $config.sourceRoot 'Gesruta') --output (Join-Path $run 'actividad_v1.json') --from-date $config.from --to-date $hasta --lugares (Join-Path $config.publicPath 'lugares-provincias.csv') --gps (Join-Path $root 'cache\lugares_gps.json') --triangulado $triArg --horas (Join-Path $root 'cache\horas_vehiculo_mes.json')}
    if($clave){Invoke-Opcional 'Enlace parte-conductor' {
        $pa=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $root 'scripts\export_rentabilidad_personal_v1.ps1'),'-Desde',$config.from,'-Hasta',$hasta,'-SourcePath',(Join-Path $config.sourceRoot 'PartesTrabajo\Partes 7.0.accdb'),'-OutputPath',(Join-Path $run 'personal_v1.json'))
        & $ps64 @pa
        if($LASTEXITCODE -ne 0){& $ps32 @pa}}}
    & $node (Join-Path $root 'scripts\prepare-data.mjs') $run
    if($LASTEXITCODE -ne 0){throw 'Fallo al conciliar las extracciones.'}
    $mode=if($config.scheduled){'scheduled'}else{'pending'}
    if($clave){$env:RENTABILIDAD_CLAVE_PERSONAL=$clave}else{Remove-Item Env:\RENTABILIDAD_CLAVE_PERSONAL -ErrorAction SilentlyContinue}
    try{& $node (Join-Path $root 'scripts\build.mjs') (Join-Path $run 'current.json.gz') $run $mode $config.at}
    finally{Remove-Item Env:\RENTABILIDAD_CLAVE_PERSONAL -ErrorAction SilentlyContinue}
    if($LASTEXITCODE -ne 0){throw 'Los controles del informe no cuadran. Se mantiene el corte anterior.'}
    $receipt=Get-Content -LiteralPath (Join-Path $run 'verification.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $ready=Join-Path $run 'informe.html'
    if((Get-FileHash -LiteralPath $ready -Algorithm SHA256).Hash.ToLower() -ne $receipt.sha256){throw 'El informe no coincide con la huella validada.'}
    # Sustitución en el mismo volumen: jamás abrir el HTML vigente para truncarlo.
    $target=Join-Path $config.publicPath 'informe.html'
    $incoming=Join-Path $config.publicPath ('informe.'+[guid]::NewGuid().ToString('N')+'.tmp')
    Copy-Item -LiteralPath $ready -Destination $incoming
    if(Test-Path -LiteralPath $target){[IO.File]::Replace($incoming,$target,$target+'.anterior')}else{[IO.File]::Move($incoming,$target)}
    # Marco comun de costes (tarifas, ERP): reparto contable por sociedad, ano y mes en export\costes.json (opcional; sustitucion atomica).
    Invoke-Opcional 'Costes (export)' {
        & $node (Join-Path $root 'scripts\export_costes.mjs') (Join-Path $run 'current.json.gz') (Join-Path $run 'costes.json')
        if($LASTEXITCODE -ne 0){throw 'costes'}
        $exp=Join-Path $config.publicPath 'export';if(-not (Test-Path -LiteralPath $exp)){New-Item -ItemType Directory -Path $exp | Out-Null}
        $pubc=Join-Path $exp 'costes.json';$tmpc=Join-Path $exp ('costes.'+[guid]::NewGuid().ToString('N')+'.tmp')
        Copy-Item -LiteralPath (Join-Path $run 'costes.json') -Destination $tmpc -Force
        if(Test-Path -LiteralPath $pubc){[IO.File]::Replace($tmpc,$pubc,$pubc+'.anterior')}else{[IO.File]::Move($tmpc,$pubc)}
    }
    $last=(Get-Date).ToString('o');$dataTo=$hasta
    $state=if($config.scheduled){'ok'}else{'pending'}
    $faltan=if($script:avisos.Count){' Sin datos en esta lectura: '+($script:avisos -join ', ')+' (se indica arriba en el informe).'}else{''}
    $message=if($config.scheduled){'Lectura completada en '+$env:COMPUTERNAME+'. Controles correctos.'+$faltan+' Las discrepancias entre fuentes siguen señaladas en Conciliación.'}else{'Lectura manual comprobada. La tarea nocturna todavia NO esta activada.'+$faltan}
    Write-RentabilidadStatus -PublicPath $config.publicPath -State $state -Message $message -LastSuccess $last -DataTo $dataTo -At $config.at -RunHost $env:COMPUTERNAME -Sources $(if($receipt.sourcesText){$receipt.sourcesText}else{'GesRuta + Access'})
    Write-Output 'Publicacion correcta. Los sistemas de origen no se han modificado.'
}catch{
    $code=1
    Write-Output ('ERROR: '+$_.Exception.Message)
    Write-RentabilidadStatus -PublicPath $config.publicPath -State error -Message ('No se completo la lectura. Se mantiene el ultimo informe correcto; consulte el registro privado en '+$logRoot+'.') -LastSuccess $last -DataTo $dataTo -At $config.at -RunHost $env:COMPUTERNAME -Sources $(if($old.sources){$old.sources}else{'GesRuta + Access'})
}finally{
    Stop-Transcript|Out-Null
    $lock.Dispose()
    # Datos personales (nombres y sueldos): fuera del disco en cuanto termina la ejecución, salga bien o mal.
    foreach($f in 'nomina_detalle.json','personal_v1.json','personal_private.json'){Remove-Item -LiteralPath (Join-Path $run $f) -Force -ErrorAction SilentlyContinue}
    # Red de seguridad: las copias de Access (llevan datos de personal) las borra cada extractor; si alguna quedo, fuera aqui.
    if(Test-Path -LiteralPath $run){Get-ChildItem -LiteralPath $run -File | Where-Object {$_.Name -match '^access-(copia|personal)-[a-f0-9]{32}\.(accdb|laccdb)$'} | Remove-Item -Force -ErrorAction SilentlyContinue}
    # Solo se limpian ejecuciones propias antiguas, con rutas absolutas comprobadas.
    $limit=(Get-Date).AddDays(-14)
    $baseFull=[IO.Path]::GetFullPath($workRoot).TrimEnd('\')+'\'
    Get-ChildItem -LiteralPath $workRoot -Directory | Where-Object {$_.LastWriteTime -lt $limit -and $_.Name -match '^\d{8}-\d{6}-[a-f0-9]{32}$'} | ForEach-Object {
        if([IO.Path]::GetFullPath($_.FullName).StartsWith($baseFull,[StringComparison]::OrdinalIgnoreCase)){Remove-Item -LiteralPath $_.FullName -Recurse -Force}
    }
    Get-ChildItem -LiteralPath $logRoot -File -Filter '*.log' | Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-90)} | Remove-Item -Force
}
exit $code
