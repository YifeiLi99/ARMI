[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$AdminConfig,
    [ValidateSet('Start', 'Stop', 'Status')]
    [string]$Action = 'Status',
    [string]$AdminExecutable
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$entryArguments = @()
if ([string]::IsNullOrWhiteSpace($AdminExecutable)) {
    $AdminExecutable = Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'
    $entryArguments = @('-m', 'armi_app')
}
if (-not (Test-Path -LiteralPath $AdminExecutable -PathType Leaf)) {
    throw 'PG-NATIVE-TOOLS: specify the installed ARMI.exe with -AdminExecutable'
}
$config = (Resolve-Path -LiteralPath $AdminConfig).Path
& $AdminExecutable @entryArguments cli admin --config $config $Action.ToLowerInvariant() --json '{"component":"postgresql"}' | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'PG-NATIVE-CONTROL: the bound Admin operation failed' }
