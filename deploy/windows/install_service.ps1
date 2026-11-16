# Install this app as a Windows Service using NSSM.
#
# The service is named after service.name in <AppDir>\config\settings.yaml, so
# several copies (staging, uat, demo) can be installed side by side, each from
# its own folder with its own settings.yaml.
#
# Usage (run in an elevated PowerShell):
#   .\install_service.ps1 -AppDir "C:\Services\data-processing-uat" -Nssm "C:\tools\nssm.exe"
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [string]$Nssm = "nssm.exe",
    # Where NSSM writes service.out.log / service.err.log.
    # Default: $env:ProgramData\<service name>\logs
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AppDir)) {
    throw "AppDir '$AppDir' does not exist. Copy the project there first."
}
$AppDir = (Resolve-Path $AppDir).Path.TrimEnd('\')
$settings = Join-Path $AppDir "config\settings.yaml"
if (-not (Test-Path $settings)) {
    throw "No settings file at '$settings'."
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
$python = Join-Path $venv "Scripts\python.exe"

# The service name comes from settings.yaml (read with the venv's PyYAML).
$readName = "import sys, yaml; c = yaml.safe_load(open(sys.argv[1], encoding='utf-8')) or {}; print((c.get('service') or {}).get('name') or '')"
$ServiceName = ("" + (& $python -c $readName $settings)).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not read service.name from '$settings'."
}
if ($ServiceName -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "service.name '$ServiceName' in '$settings' must be set and use only letters, digits, '_', '-' or '.'."
}

# Never take over a service that belongs to another folder (another instance,
# or an unrelated Windows service with the same name).
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    $params = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
    $existingDir = (Get-ItemProperty -Path $params -Name AppDirectory -ErrorAction SilentlyContinue).AppDirectory
    if (-not $existingDir -or $existingDir.TrimEnd('\') -ne $AppDir) {
        throw "A service named '$ServiceName' already exists for '$existingDir'. Give this copy a different service.name in '$settings', or uninstall that service first."
    }
}

if (-not $LogDir) { $LogDir = Join-Path $env:ProgramData "$ServiceName\logs" }
New-Item -ItemType Directory -Force $LogDir | Out-Null

$main = Join-Path $AppDir "main.pyc"   # compiled package
if (-not (Test-Path $main)) { $main = Join-Path $AppDir "main.py" }   # source checkout

Write-Host "Installing service '$ServiceName' from '$AppDir'"

# Remove a previous install of this same instance, then install fresh.
try { & $Nssm stop     $ServiceName | Out-Null } catch {}
try { & $Nssm remove   $ServiceName confirm | Out-Null } catch {}

& $Nssm install $ServiceName $python $main
& $Nssm set $ServiceName AppDirectory $AppDir
& $Nssm set $ServiceName Description "$ServiceName (data-processing supervisor + units) from $AppDir"
# The app's own log file is logging.path in settings.yaml. $LogDir only holds
# NSSM's capture of the console (startup errors, crash tracebacks).
& $Nssm set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1"
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
