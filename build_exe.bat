@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1" %*
set "BUILD_RC=%ERRORLEVEL%"
if not "%BUILD_RC%"=="0" pause
exit /b %BUILD_RC%
