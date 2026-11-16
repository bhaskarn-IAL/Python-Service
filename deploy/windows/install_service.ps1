# Install data-processing as a Windows Service using NSSM.
# Usage (run in an elevated PowerShell):
#   .\install_service.ps1 -AppDir "C:\Services\data-processing" -Nssm "C:\tools\nssm.exe"
param(
    [string]$ServiceName = "data-processing",
    [Parameter(Mandatory = $true)][string]$AppDir,
    [string]$Nssm = "nssm.exe",
    [string]$LogDir = "$env:ProgramData\data-processing\logs"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AppDir)) {
    throw "AppDir '$AppDir' does not exist. Copy the project there first."
}

# A compiled package (from build.py) only loads on the Python version that built it.
$buildInfo = Join-Path $AppDir "BUILD_INFO.json"
if (Test-Path $buildInfo) {
    $needed = (Get-Content $buildInfo -Raw | ConvertFrom-Json).python
    $found = & python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
    if ($found -ne $needed) {
        throw "This package was built for Python $needed, but 'python' here is $found. Install Python $needed first."
    }
}

$venv = Join-Path $AppDir "venv"
if (-not (Test-Path $venv)) {
    Write-Host "Creating venv..."
    python -m venv $venv
    & "$venv\Scripts\pip.exe" install --upgrade pip
    & "$venv\Scripts\pip.exe" install -r (Join-Path $AppDir "requirements.txt")
}

New-Item -ItemType Directory -Force $LogDir | Out-Null

$python = Join-Path $venv "Scripts\python.exe"
$main   = Join-Path $AppDir "main.pyc"   # compiled package
if (-not (Test-Path $main)) { $main = Join-Path $AppDir "main.py" }   # source checkout

# Remove any previous install, then install fresh.
try { & $Nssm stop     $ServiceName | Out-Null } catch {}
try { & $Nssm remove   $ServiceName confirm | Out-Null } catch {}

& $Nssm install $ServiceName $python $main
& $Nssm set $ServiceName AppDirectory $AppDir
# SERVICE_LOG_CONSOLE=0: NSSM already captures stderr into service.err.log,
# so console logging would only duplicate every line there.
& $Nssm set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1" "SERVICE_LOG_DIR=$LogDir" "SERVICE_LOG_CONSOLE=0"
& $Nssm set $ServiceName AppStdout (Join-Path $LogDir "service.out.log")
& $Nssm set $ServiceName AppStderr (Join-Path $LogDir "service.err.log")
& $Nssm set $ServiceName AppRotateFiles 1
& $Nssm set $ServiceName AppRotateBytes 5242880
& $Nssm set $ServiceName Start SERVICE_AUTO_START
& $Nssm set $ServiceName AppExit Default Restart
& $Nssm set $ServiceName AppRestartDelay 5000
# Wait up to 30 s after Ctrl+C before force-killing (NSSM default is 1.5 s),
# so every unit gets to run teardown(). Matches TimeoutStopSec on Linux.
& $Nssm set $ServiceName AppStopMethodConsole 30000

& $Nssm start $ServiceName
& $Nssm status $ServiceName
