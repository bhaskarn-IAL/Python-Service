@echo off
rem Build the deployable package: compiles the project to .pyc (no .py source)
rem and zips it into dist\<name>-<version>-py<XY>.zip, using build.py.
rem
rem Usage: double-click this file, or in a Command Prompt:
rem   build_project.cmd [path\to\python.exe]
rem
rem Which Python builds the package matters: the target machine needs the
rem same Python version (e.g. 3.12) to run it. Without an argument it uses
rem the project's .venv if there is one, otherwise 'python' on the PATH.
rem No administrator rights needed. The window stays open until you press a key.

setlocal EnableExtensions
set "RC=1"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not "%~1"=="" (
    set "PY=%~f1"
) else if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

if /i "%PY%"=="python" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: 'python' was not found. Install Python, or pass the path to python.exe.
        goto :end
    )
) else if not exist "%PY%" (
    echo ERROR: "%PY%" does not exist.
    goto :end
)

echo Building with:
"%PY%" -c "import sys; print('  ' + sys.executable); print('  Python %%d.%%d' %% sys.version_info[:2])"
if errorlevel 1 goto :end
echo.

pushd "%ROOT%"
"%PY%" build.py
set "RC=%errorlevel%"
popd

:end
echo.
if "%RC%"=="0" (
    echo Build finished. Copy the zip above to the target machine, unzip it, then run
    echo deploy\windows\install_service.cmd from the unzipped folder.
) else (
    echo Build FAILED. See the messages above.
)
echo Press any key to close . . .
pause >nul
exit /b %RC%
