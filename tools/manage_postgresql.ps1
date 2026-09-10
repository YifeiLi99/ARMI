[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$AdminConfig,
    [ValidateSet('Start', 'Stop', 'Status')]
    [string]$Action = 'Status',
    [string]$AdminExecutable = (Join-Path $env:LOCALAPPDATA 'Programs/ARMI/armi-admin.exe')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not (Test-Path -LiteralPath $AdminExecutable -PathType Leaf)) {
    throw 'PG-NATIVE-TOOLS: specify the installed armi-admin.exe with -AdminExecutable'
}
$config = (Resolve-Path -LiteralPath $AdminConfig).Path
& $AdminExecutable --config $config $Action.ToLowerInvariant() --json '{"component":"postgresql"}'
if ($LASTEXITCODE -ne 0) { throw 'PG-NATIVE-CONTROL: the bound Admin operation failed' }
