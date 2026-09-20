@echo off
rem Elegir la clave del apartado "Coste por empleado". La clave se escribe aqui, no en ningun chat.
if not exist "C:\ProgramData\RazoRentabilidad\Poner-clave-personal.ps1" (
  echo Primero hay que instalar el informe: INSTALAR EN ESTE PC.cmd
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\RazoRentabilidad\Poner-clave-personal.ps1"
echo.
pause
