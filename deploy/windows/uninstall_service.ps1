# Remove a service installed by install_service.ps1. Files and logs are kept.
#
# Usage (run in an elevated PowerShell), either:
#   .\uninstall_service.ps1 -AppDir "C:\Services\data-processing-uat"   # the service installed from that folder
#   .\uninstall_service.ps1 -ServiceName "data-processing-uat"
#
# -AppDir finds the service by the folder it was installed from, so it still
# works if service.name in settings.yaml was changed after installing.
param(
    [string]$AppDir = "",
    [string]$ServiceName = "",
    [string]$Nssm = "nssm.exe"
)
$ErrorActionPreference = "Continue"

if (-not $ServiceName) {
    if (-not $AppDir) {
        throw "Pass -AppDir (the folder the service was installed from) or -ServiceName."
    }
    $dir = $AppDir.TrimEnd('\')
    if (Test-Path $dir) { $dir = (Resolve-Path $dir).Path.TrimEnd('\') }
    $found = @(
        Get-ChildItem HKLM:\SYSTEM\CurrentControlSet\Services -ErrorAction SilentlyContinue |
            Where-Object {
                $p = Get-ItemProperty -Path "$($_.PSPath)\Parameters" -Name AppDirectory -ErrorAction SilentlyContinue
                $p -and $p.AppDirectory.TrimEnd('\') -eq $dir
            } |
            ForEach-Object { $_.PSChildName }
    )
    if ($found.Count -eq 0) { throw "No service is installed from '$dir'." }
    if ($found.Count -gt 1) { throw "Several services are installed from '$dir': $($found -join ', '). Pass -ServiceName." }
    $ServiceName = $found[0]
}

Write-Host "Removing service '$ServiceName'"
& $Nssm stop   $ServiceName
& $Nssm remove $ServiceName confirm
