@echo off
setlocal EnableExtensions EnableDelayedExpansion
title MapLeads
rem Double-click to set up and start the MapLeads web app.
rem First run: finds (or installs) Python, creates .venv, installs packages.
rem Later runs: starts straight away; packages are reinstalled only when requirements change.

cd /d "%~dp0"
if defined MAPLEADS_PORT (set "PORT=%MAPLEADS_PORT%") else (set "PORT=8000")
set "URL=http://127.0.0.1:%PORT%"
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "REQ=%~dp0webapp\requirements.txt"
set "STAMP=%VENV%\.requirements-installed"

echo.
echo  ==============================
echo    MapLeads - Google Maps leads
echo  ==============================
echo.

rem --- Already running? Just open it. -------------------------------------
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%/api/v1/stats') | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo  MapLeads is already running. Opening %URL%
    start "" "%URL%"
    timeout /t 2 >nul
    exit /b 0
)

rem --- 1. Python --------------------------------------------------------
if exist "%VPY%" goto :have_venv

set "PY="
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 && set "PY=%%~C"
    )
)

if not defined PY (
    echo  Python 3.9 or newer was not found on this computer.
    where winget >nul 2>&1
    if errorlevel 1 goto :no_python
    echo.
    choice /c YN /m " Install Python 3.12 now with winget"
    if errorlevel 2 goto :no_python
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :no_python
    rem winget does not update PATH for this window; use the per-user install path.
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if not exist "!PY!" goto :python_restart
    set "PY="!PY!""
)

echo  [1/3] Creating the app environment (.venv) with: %PY%
%PY% -m venv "%VENV%"
if errorlevel 1 (
    echo.
    echo  Could not create the environment. Make sure Python is installed with "venv".
    goto :fail
)

:have_venv
rem --- 2. Packages (only when requirements.txt changed) ----------------
set "NEED_INSTALL=1"
if exist "%STAMP%" (
    fc /b "%REQ%" "%STAMP%" >nul 2>&1 && set "NEED_INSTALL=0"
)
if "%NEED_INSTALL%"=="1" (
    echo  [2/3] Installing packages - first run takes a minute...
    "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip >nul 2>&1
    "%VPY%" -m pip install --disable-pip-version-check -q -r "%REQ%"
    if errorlevel 1 (
        echo.
        echo  Package install failed. Check your internet connection and run this file again.
        goto :fail
    )
    copy /y "%REQ%" "%STAMP%" >nul
) else (
    echo  [2/3] Packages are up to date.
)

rem --- 3. Start -----------------------------------------------------------
echo  [3/3] Starting MapLeads at %URL%
echo.
echo  Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.
echo.
"%VPY%" -m webapp --port %PORT% %MAPLEADS_ARGS%
if errorlevel 1 (
    echo.
    echo  MapLeads stopped with an error ^(see above^).
    echo  If it says the port is in use, another program is using port %PORT%.
    goto :fail
)
exit /b 0

:python_restart
echo.
echo  Python was installed. Close this window and double-click start-mapleads.bat again.
goto :fail

:no_python
echo.
echo  Please install Python 3.12 from https://www.python.org/downloads/
echo  ^(tick "Add python.exe to PATH" during setup^), then run this file again.
start "" "https://www.python.org/downloads/"

:fail
echo.
pause
exit /b 1
