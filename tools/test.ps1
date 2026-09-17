[CmdletBinding()]
param(
    [switch]$All,
    [string[]]$Group,
    [switch]$Database,
    [switch]$List,
    [ValidateRange(1, 32)]
    [int]$Jobs = [Math]::Min(14, [Math]::Max(1, [Environment]::ProcessorCount - 2)),
    [ValidateRange(1, 16)]
    [int]$DatabaseJobs = 4
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'TEST-TOOL-MISSING: prepare the managed workspace environment first.'
}
$arguments = @('-B', '-m', 'tools.run_tests', '--jobs', $Jobs, '--database-jobs', $DatabaseJobs)
if ($All) { $arguments += '--all' }
if ($Database) { $arguments += '--database' }
if ($List) { $arguments += '--list' }
foreach ($name in $Group) { $arguments += @('--group', $name) }
Push-Location -LiteralPath $root
try {
    & $python @arguments
    $result = $LASTEXITCODE
}
finally { Pop-Location }
exit $result
