@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Erstellen.ps1" %*
exit /b %errorlevel%
