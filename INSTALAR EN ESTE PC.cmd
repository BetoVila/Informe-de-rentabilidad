@echo off
rem Instala o actualiza el programa en el PC de Roberto (donde estan las claves de Movertis y Locatel).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Instalar.ps1" -Modo Pc
echo.
pause
