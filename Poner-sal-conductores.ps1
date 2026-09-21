param([switch]$Nueva)
# Crea la «sal» secreta con la que se protegen los identificadores de los conductores (el DNI que lleva dentro la tarjeta del
# tacógrafo). La genera el propio programa al azar: nadie la elige ni la ve y no pasa por ningún chat. Queda cifrada con DPAPI
# para este usuario de Windows en este PC. Sin ella, las horas por conductor no se enlazan con la ficha de cada uno.
# Si se pierde (p. ej. al reinstalar el PC) no pasa nada: se crea otra y en la siguiente lectura se recalcula todo.
$ErrorActionPreference='Stop'
try{
    $private='C:\ProgramData\RazoRentabilidad'
    $configPath=Join-Path $private 'config.json'
    if(-not(Test-Path -LiteralPath $configPath)){throw 'Primero hay que instalar el informe (INSTALAR EN ESTE PC.cmd).'}
    $file=Join-Path $private 'sal-conductores.bin'
    if((Test-Path -LiteralPath $file) -and -not $Nueva){
        Write-Output 'La sal de conductores ya existe en este PC. No se ha cambiado nada.'
        Write-Output '(Para crear otra nueva, ejecutar con -Nueva: se recalcula todo en la siguiente lectura.)'
        exit 0
    }
    $raw=New-Object byte[] 32
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
    try{$rng.GetBytes($raw)}finally{$rng.Dispose()}
    Add-Type -AssemblyName System.Security
    $bytes=[Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes([Convert]::ToBase64String($raw)),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    [Array]::Clear($raw,0,$raw.Length)
    [IO.File]::WriteAllBytes($file,$bytes)
    $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json
    $config|Add-Member -NotePropertyName salConductoresFile -NotePropertyValue $file -Force
    $config|Add-Member -NotePropertyName salConductoresAlcance -NotePropertyValue 'CurrentUser' -Force
    [IO.File]::WriteAllText($configPath,($config|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))
    Write-Output 'Sal de conductores creada y guardada cifrada para este usuario de Windows.'
    Write-Output 'No hay que apuntar nada. Se usara a partir de la proxima lectura.'
}catch{
    Write-Output ('NO GUARDADA: '+$_.Exception.Message)
    exit 1
}
