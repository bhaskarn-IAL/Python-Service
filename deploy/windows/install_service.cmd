@echo off
rem Install this app as a Windows Service using NSSM.
rem
rem Everything comes from <app folder>\config\settings.yaml:
rem   service.name  -> the Windows service name, so several copies (staging,
rem                    uat, demo) can be installed side by side, each from its
rem                    own folder with its own settings.yaml
rem   logging.path  -> the app's log file; its folder is created, and NSSM's
rem                    console capture (<service.name>.out.log/.err.log) goes there
rem
rem Usage: right-click this file > "Run as administrator" to install the app
rem folder it sits in. Or, in a Command Prompt opened as Administrator:
rem   install_service.cmd ["C:\Services\data-processing-uat"] [C:\tools\nssm.exe]
rem
rem The window stays open at the end until you press a key.
rem The work is done by service_setup.py next to this file.

setlocal EnableExtensions
set "RC=1"

rem Default: the app folder this script belongs to (deploy\windows\..\..).
if "%~1"=="" (
    for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
) else (
    set "APP_DIR=%~f1"
)
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
set "NSSM=%~2"
if not defined NSSM set "NSSM=nssm.exe"
set "SETUP=%~dp0service_setup.py"

echo Installing the service from "%APP_DIR%"
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run this as Administrator: right-click it and choose "Run as administrator".
    goto :end
)

if not exist "%APP_DIR%\config\settings.yaml" (
    echo ERROR: No settings file at "%APP_DIR%\config\settings.yaml". Copy the project there first.
    goto :end
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: 'python' was not found. Install Python and try again.
    goto :end
)

rem A compiled package only loads on the Python version that built it.
python "%SETUP%" check-python "%APP_DIR%"
if errorlevel 1 goto :end

set "VENV_PY=%APP_DIR%\venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Creating venv...
    python -m venv "%APP_DIR%\venv"
    if errorlevel 1 goto :venv_failed
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 goto :venv_failed
    "%VENV_PY%" -m pip install -r "%APP_DIR%\requirements.txt"
    if errorlevel 1 goto :venv_failed
)

"%VENV_PY%" "%SETUP%" install "%APP_DIR%" "%NSSM%"
set "RC=%errorlevel%"
goto :end

:venv_failed
echo ERROR: Creating the venv failed; removing the half-made "%APP_DIR%\venv".
rmdir /s /q "%APP_DIR%\venv" 2>nul
goto :end

:end
echo.
if "%RC%"=="0" (echo Install finished.) else (echo Install FAILED. See the messages above.)
echo Press any key to close . . .
pause >nul
exit /b %RC%
