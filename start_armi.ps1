[CmdletBinding()]
param(
    [string]$AdminConfig = $env:ARMI_ADMIN_CONFIG,
    [string]$AdminExecutable,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'ARMI-START-POWERSHELL: PowerShell 7 or newer is required.'
}
if ([string]::IsNullOrWhiteSpace($AdminConfig)) {
    throw 'ARMI-START-BINDING: specify -AdminConfig or ARMI_ADMIN_CONFIG.'
}
$entryArguments = @()
if ([string]::IsNullOrWhiteSpace($AdminExecutable)) {
    $AdminExecutable = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $entryArguments = @('-m', 'armi_app')
}
$executable = (Get-Command $AdminExecutable -CommandType Application -ErrorAction Stop).Source
$binding = [IO.Path]::GetFullPath($AdminConfig)
$raw = @(& $executable @entryArguments cli admin --config $binding start)
$result = ($raw -join "`n") | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    $raw | Write-Output
    exit $LASTEXITCODE
}
if ($OpenBrowser) {
    $configRaw = @(& $executable @entryArguments cli admin --config $binding configuration --json '{"action":"read"}')
    if ($LASTEXITCODE -ne 0) {
        throw 'ARMI-START-CONFIG: unable to resolve the bound Creator Web address.'
    }
    $config = ($configRaw -join "`n") | ConvertFrom-Json
    $creator = $config.result.effective_on_next_start.creator
    Start-Process -FilePath "http://$($creator.bind_host):$($creator.port)/ui/"
}
$result | ConvertTo-Json -Depth 20
