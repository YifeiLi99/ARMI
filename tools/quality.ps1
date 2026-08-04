[CmdletBinding()]
param(
    [string[]]$Gate,
    [switch]$Release,
    [string]$ToolRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) '.armi-tools')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'QLT-POWERSHELL: PowerShell 7 or newer is required.'
}
if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'QLT-PLATFORM: only Windows x86_64 is supported.'
}

$root = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$resolvedToolRoot = [IO.Path]::GetFullPath($ToolRoot)
$managedPython = Join-Path $resolvedToolRoot 'installs/python/cpython-3.14.6-windows-x86_64-none/python.exe'
if (-not (Test-Path -LiteralPath $managedPython -PathType Leaf)) {
    Write-Error 'QLT-TOOL-MISSING: isolated CPython 3.14.6 is absent.'
    exit 2
}

$arguments = @(
    '-B',
    (Join-Path $root 'tools/quality.py'),
    '--root',
    $root,
    '--tool-root',
    $resolvedToolRoot
)
foreach ($gateId in $Gate) {
    $arguments += @('--gate', $gateId)
}
if ($Release) {
    $arguments += '--release'
}

$previousPythonIoEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONIOENCODING = 'utf-8:replace'
    & $managedPython @arguments
    $qualityExitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}
exit $qualityExitCode
