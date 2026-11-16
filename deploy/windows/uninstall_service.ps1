param(
    [string]$ServiceName = "data-processing",
    [string]$Nssm = "nssm.exe"
)
$ErrorActionPreference = "Continue"
& $Nssm stop   $ServiceName
& $Nssm remove $ServiceName confirm
