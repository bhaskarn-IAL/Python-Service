@echo off
rem Remove a service installed by install_service.cmd. Files and logs are kept.
rem
rem Usage: right-click this file > "Run as administrator" to remove the service
rem installed from the app folder it sits in. Or, in a Command Prompt opened as
rem Administrator, either:
rem   uninstall_service.cmd ["C:\Services\data-processing-uat"] [C:\tools\nssm.exe]
rem       removes the service installed from that folder, even if service.name
rem       in its settings.yaml was changed after installing
rem   uninstall_service.cmd /name data-processing-uat [C:\tools\nssm.exe]
rem
rem The window stays open at the end until you press a key.
rem The work is done by service_setup.py next to this file.

setlocal EnableExtensions
set "RC=1"
set "SETUP=%~dp0service_setup.py"

if /i "%~1"=="/name" if "%~2"=="" goto :usage

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run this as Administrator: right-click it and choose "Run as administrator".
    goto :end
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: 'python' was not found. Install Python and try again.
    goto :end
)

if /i "%~1"=="/name" (
    set "NSSM=%~3"
    if not defined NSSM set "NSSM=nssm.exe"
    goto :by_name
)

rem Default: the app folder this script belongs to (deploy\windows\..\..).
if "%~1"=="" (
    for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
) else (
    set "APP_DIR=%~f1"
)
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
set "NSSM=%~2"
if not defined NSSM set "NSSM=nssm.exe"
echo Removing the service installed from "%APP_DIR%"
echo.
python "%SETUP%" uninstall "%APP_DIR%" "%NSSM%"
set "RC=%errorlevel%"
goto :end

:by_name
echo Removing the service "%~2"
echo.
python "%SETUP%" uninstall --name "%~2" "%NSSM%"
set "RC=%errorlevel%"
goto :end

:usage
echo Usage: %~nx0 ["C:\Services\data-processing-uat"] [path\to\nssm.exe]
echo    or: %~nx0 /name data-processing-uat [path\to\nssm.exe]
goto :end

:end
echo.
if "%RC%"=="0" (echo Uninstall finished.) else (echo Uninstall FAILED. See the messages above.)
echo Press any key to close . . .
pause >nul
exit /b %RC%
