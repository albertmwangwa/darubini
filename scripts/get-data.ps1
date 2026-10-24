# Download Darubini datasets on Windows (the Makefile equivalent of `make data`).
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\get-data.ps1                 # core tier
#   powershell -ExecutionPolicy Bypass -File scripts\get-data.ps1 -Tier extended
#   powershell -ExecutionPolicy Bypass -File scripts\get-data.ps1 -Tier large -AcceptLicences
param(
    [ValidateSet("core", "extended", "large")]
    [string]$Tier = "core",
    [switch]$AcceptLicences
)
$ErrorActionPreference = "Stop"
$cli = ".\.venv\Scripts\darubini.exe"
if (-not (Test-Path $cli)) { Write-Error "Run scripts\setup.ps1 first." }

$dlArgs = @("download", "--tier", $Tier)
if ($AcceptLicences) { $dlArgs += "--accept-licences" }
& $cli @dlArgs
& $cli verify
