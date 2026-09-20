@echo off
if /I not "%COMPUTERNAME%"=="SERVIDOR" (
  echo Este paso se abre DENTRO de SERVIDOR, no en este PC.
  echo Para instalar en el PC de Roberto use INSTALAR EN ESTE PC.cmd
  pause
  exit /b 1
)
powershell.exe -NoProfile -Command "Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList '-NoProfile -NoExit -ExecutionPolicy Bypass -File ""%~dp0Instalar.ps1"" -Modo Servidor' -Wait"
