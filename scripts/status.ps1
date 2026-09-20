function Write-RentabilidadStatus {
    param([string]$PublicPath,[string]$State,[string]$Message,[string]$LastSuccess,[string]$DataTo,[string]$At='03:00',[string]$RunHost=$env:COMPUTERNAME,[string]$Sources='GesRuta + Access')
    $stamp=(Get-Date).ToString('o')
    $esc={param($s) [System.Net.WebUtility]::HtmlEncode([string]$s)}
    $title=switch($State){'ok'{'Lectura completada'} 'error'{'Lectura fallida: se conserva el informe anterior'} 'running'{'Actualizando datos'} default{'Actualizacion nocturna pendiente de activar'}}
    $payload=@{state=$State;message=$Message;checkedAt=$stamp;lastSuccess=$LastSuccess;dataTo=$DataTo;scheduledAt=$At;host=$RunHost;sources=$Sources}
    $html=@"
<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rentabilidad | Estado de la actualizacion</title>
<style>*{box-sizing:border-box}body{margin:0;background:#edf2f7;color:#172943;font:16px/1.6 Segoe UI,Arial,sans-serif}header{background:#12243e;color:white;padding:28px 6vw;letter-spacing:.06em}main{max-width:900px;margin:50px auto;padding:36px;background:white;border-radius:20px;box-shadow:0 10px 45px #152b4510}h1{font-size:32px;line-height:1.2}small{color:#66768d}.status{padding:20px;background:#fff4da;border-left:4px solid #d6a036;border-radius:8px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:28px 0}.grid div{background:#f4f7fa;padding:20px;border-radius:12px}.button{display:inline-block;padding:14px 24px;border-radius:8px;background:#245fc6;color:white;text-decoration:none;font-weight:600}a{color:#245fc6}code{overflow-wrap:anywhere}@media(max-width:600px){main{margin:15px;padding:24px}.grid{grid-template-columns:1fr}}footer{margin-top:30px;color:#61718a;font-size:14px}</style>
<header>RAZO + AGETRANS &nbsp; / &nbsp; RENTABILIDAD</header><main><small>ESTADO DE LA ACTUALIZACION</small><h1>$(& $esc $title)</h1><div class="status">$(& $esc $Message)</div>
<div class="grid"><div><small>Ultima lectura correcta</small><br><strong>$(& $esc $(if($LastSuccess){$LastSuccess}else{'Pendiente'}))</strong></div><div><small>Datos incluidos hasta</small><br><strong>$(& $esc $DataTo)</strong></div><div><small>Horario previsto</small><br><strong>$(& $esc $At) &middot; lo ejecuta $(& $esc $RunHost)</strong></div><div><small>Fuentes de la ultima lectura</small><br><strong>$(& $esc $Sources)</strong></div></div>
<a class="button" href="informe.html">Abrir informe con filtros &rarr;</a><p><a href="estado.html">Volver a cargar este estado</a></p><h2>Un unico informe para la oficina</h2><p>El acceso abre la copia del servidor, no una copia de cada PC. Los segmentadores se calculan en su navegador. Si el servidor o la red no estan disponibles, este acceso no abrira.</p><p>Las fuentes que un dia no estan disponibles se indican arriba en el propio informe; nunca se sustituye un dato que falta por un cero.</p><footer>Comprobado: $(& $esc $stamp). Sin publicacion en Internet. Si una lectura falla, se conserva el ultimo informe valido. La carpeta <b>LEEME.txt</b> explica la activacion y el mantenimiento.</footer></main></html>
"@
    $utf8=New-Object System.Text.UTF8Encoding($false)
    foreach($item in @(@('estado.json',($payload|ConvertTo-Json -Depth 5)),@('estado.html',$html))){
        $target=Join-Path $PublicPath $item[0]
        $temp=$target+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
        [IO.File]::WriteAllText($temp,$item[1],$utf8)
        # PowerShell 5 convierte $null en una ruta vacía en esta sobrecarga.
        # Una copia anterior con nombre explícito mantiene además la recuperación.
        if(Test-Path -LiteralPath $target){[IO.File]::Replace($temp,$target,$target+'.anterior')}else{[IO.File]::Move($temp,$target)}
    }
}
