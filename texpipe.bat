@echo off
rem ============================================================================
rem  texpipe launcher (Windows .bat)
rem  Double-click this file to start the texture channel tool GUI.
rem  - Detects Python (py launcher first, then python on PATH)
rem  - Explains clearly if Python is missing / too old / only a Store stub
rem  - Auto-installs missing Python packages on first run
rem  - Launches the GUI
rem ============================================================================

setlocal
cd /d "%~dp0"

set "PY="
set "PY_STUB="
rem Try `py` launcher first (skips Microsoft Store stub, picks the real install)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        rem A real python works; a Microsoft Store placeholder (WindowsApps)
        rem just pops the Store window and exits, so flag it for the error msg.
        where python 2>nul | findstr /i "WindowsApps" >nul 2>&1
        if not errorlevel 1 set "PY_STUB=1"
        python --version >nul 2>&1
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY goto :no_python

rem texpipe needs Python 3.10+
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :old_python

echo.
echo  [info] Using Python: %PY%
%PY% --version

echo  [check] Verifying required packages (numpy / Pillow / PySide6 / PNG / TIFF / EXR)...
%PY% -c "import numpy, PIL, PySide6, png, tifffile, OpenEXR" >nul 2>&1
if errorlevel 1 goto :install_deps
goto :run_gui

:install_deps
echo  [setup] Missing packages detected. Installing from requirements.txt ...
echo.
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
echo.

rem Optional: Skybox Noise plugin uses numba for 25-40x speedup.
rem Missing numba is OK (falls back to numpy); install failure is non-fatal.
echo  [optional] Trying to install numba (optional, ~150MB, skybox-noise speedup)...
%PY% -m pip install --quiet numba >nul 2>&1
if errorlevel 1 (
    echo  [info] numba install skipped (skybox-noise will use numpy fallback)
) else (
    echo  [ok] numba ready
)
echo.
goto :run_gui

:run_gui
echo  [start] Launching texpipe GUI ...
echo.
%PY% -m src.ui.main
goto :end

:no_python
echo.
echo  [error] Python 3 was not found on this computer.
if defined PY_STUB (
    echo  A Microsoft Store placeholder was detected, but a real Python is NOT
    echo  installed. The placeholder alone cannot run texpipe.
) else (
    echo  texpipe is a Python program and needs Python to start.
)
echo.
echo  Install Python 3.10+ with ONE of these options, then run this file again:
echo.
echo    [Option 1 - recommended] Windows package manager, one command:
echo       winget install Python.Python.3.12
echo.
echo    [Option 2] Manual installer - tick "Add python.exe to PATH":
echo       https://www.python.org/downloads/
echo.
echo    [Option 3] Microsoft Store - search for "Python 3.12"
echo.
echo  After installing, close this window and double-click texpipe.bat again.
echo.
pause
exit /b 1

:old_python
echo.
echo  [error] texpipe needs Python 3.10+, but an older version was found:
%PY% --version
echo.
echo  Please install Python 3.10+ (https://www.python.org/downloads/)
echo  and run this file again.
echo.
pause
exit /b 1

:pip_failed
echo.
echo  [error] pip install failed. Check your network and try again.
pause
exit /b 1

:end
endlocal
