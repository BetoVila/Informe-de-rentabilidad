# Elige la clave del apartado «Coste por empleado» del informe. La escribe QUIEN LA ELIGE, aqui, en su ventana: no se pasa por el chat.
# La clave no se guarda en claro: queda cifrada con DPAPI para este usuario de Windows en este PC. El informe la usa para cifrar
# los datos de personal (nombres y costes) y no la publica ni la enseña. Sin clave, esos datos ni se leen ni salen en el informe.
$ErrorActionPreference='Stop'
try{
    $private='C:\ProgramData\RazoRentabilidad'
    $configPath=Join-Path $private 'config.json'
    if(-not(Test-Path -LiteralPath $configPath)){throw 'Primero hay que instalar el informe (INSTALAR EN ESTE PC.cmd).'}
    Write-Output 'Elija la clave del apartado de personal (coste por empleado). Minimo 10 caracteres.'
    Write-Output 'Sin esta clave nadie puede ver sueldos en el informe. Apuntela: no se puede recuperar.'
    $a=Read-Host 'Clave' -AsSecureString
    $b=Read-Host 'Repita la clave' -AsSecureString
    $pa=[Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($a))
    $pb=[Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($b))
    if($pa -ne $pb){throw 'Las dos claves no coinciden. No se ha guardado nada.'}
    if($pa.Length -lt 10){throw 'La clave es demasiado corta (minimo 10 caracteres). No se ha guardado nada.'}
    Add-Type -AssemblyName System.Security
    $bytes=[Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($pa),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    $file=Join-Path $private 'clave-personal.bin'
    [IO.File]::WriteAllBytes($file,$bytes)
    $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json
    $config|Add-Member -NotePropertyName clavePersonalFile -NotePropertyValue $file -Force
    $config|Add-Member -NotePropertyName clavePersonalAlcance -NotePropertyValue 'CurrentUser' -Force
    [IO.File]::WriteAllText($configPath,($config|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))
    Write-Output ''
    Write-Output 'Clave guardada (cifrada para este usuario de Windows). El apartado aparece en la proxima lectura:'
    Write-Output 'a las 03:00 o al pulsar «Rentabilidad - Actualizar ahora». Para cambiarla, ejecute esto otra vez.'
}catch{
    Write-Output ('NO GUARDADA: '+$_.Exception.Message)
    exit 1
}
