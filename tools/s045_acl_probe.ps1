[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string[]]$Readable,

    [Parameter(Mandatory)]
    [string[]]$Forbidden,

    [Parameter(Mandatory)]
    [string]$WritableDirectory,

    [Parameter(Mandatory)]
    [string]$ResultPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Test-Readable {
    param([string]$Path)
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $stream.Dispose()
        return $true
    } catch [UnauthorizedAccessException] {
        return $false
    } catch [IO.IOException] {
        return $false
    }
}

$readablePassed = @($Readable | ForEach-Object { Test-Readable -Path $_ }) -notcontains $false
$forbiddenPassed = @($Forbidden | ForEach-Object { -not (Test-Readable -Path $_) }) -notcontains $false
$writePassed = $false
$marker = Join-Path $WritableDirectory ('.s045-probe-' + [guid]::NewGuid().ToString('N'))
try {
    [IO.File]::WriteAllText($marker, 'probe', [Text.UTF8Encoding]::new($false))
    $writePassed = Test-Path -LiteralPath $marker -PathType Leaf
} finally {
    if (Test-Path -LiteralPath $marker -PathType Leaf) {
        Remove-Item -LiteralPath $marker -Force -ErrorAction Stop
    }
}

$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$result = [ordered]@{
    schema_version = 'armi.s045-acl-probe.v1'
    sid = $sid
    readable_passed = $readablePassed
    forbidden_passed = $forbiddenPassed
    writable_passed = $writePassed
    passed = $readablePassed -and $forbiddenPassed -and $writePassed
}
[IO.File]::WriteAllText(
    $ResultPath,
    (($result | ConvertTo-Json -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
if (-not $result.passed) { exit 1 }
