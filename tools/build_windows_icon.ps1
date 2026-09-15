[CmdletBinding()]
param([Parameter(Mandatory)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$icons = Join-Path $root 'apps/armi-admin/src/armi_admin/icon_resources'
& 'C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/rc.exe' /nologo /I $icons /fo $OutputPath (Join-Path $PSScriptRoot 'windows/armi.rc')
if ($LASTEXITCODE -ne 0) { throw 'ARMI-ICON-COMPILE' }
