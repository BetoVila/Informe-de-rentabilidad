' Arranca, sin ventana, el servidor http de las apps publicadas (servir_apps.py). Lo lanza la tarea
' "Razo - Apps por http" al iniciar sesion y cada 5 minutos: si ya esta en marcha, el servidor sale solo sin duplicar.
Set sh = CreateObject("WScript.Shell")
carpeta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
py = "C:\ProgramData\RazoRentabilidad\runtime\python\python.exe"
sh.Run """" & py & """ """ & carpeta & "\servir_apps.py""", 0, True
