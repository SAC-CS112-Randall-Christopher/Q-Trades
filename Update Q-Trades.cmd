@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Update-QTrades.ps1"
set "result=%errorlevel%"
echo.
pause
exit /b %result%
