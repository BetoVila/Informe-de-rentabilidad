@echo off
rem Crear la sal secreta que protege los identificadores de los conductores. No hay que escribir nada: se genera sola.
if not exist "C:\ProgramData\RazoRentabilidad\Poner-sal-conductores.ps1" (
  echo Primero hay que instalar el informe: INSTALAR EN ESTE PC.cmd
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\RazoRentabilidad\Poner-sal-conductores.ps1"
echo.
pause
