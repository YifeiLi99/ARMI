[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EnvironmentRoot,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $Apply) {
    throw 'ARMI-RESET-APPLY: pass -Apply to clear the approved local data directories.'
}

$rootItem = Get-Item -LiteralPath $EnvironmentRoot -Force -ErrorAction Stop
if (-not $rootItem.PSIsContainer -or
    ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'ARMI-RESET-ROOT: environment root must be a real directory.'
}
$root = $rootItem.FullName
$rootBoundary = $root.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar

if (-not (Test-Path -LiteralPath (Join-Path $root 'environment.yaml') -PathType Leaf)) {
    throw 'ARMI-RESET-IDENTITY: environment.yaml is missing.'
}

$descriptorPath = Join-Path $root 'run/runtime-process.json'
if (Test-Path -LiteralPath $descriptorPath -PathType Leaf) {
    try {
        $descriptor = Get-Content -LiteralPath $descriptorPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        $runtimePid = [int]$descriptor.pid
        if ($runtimePid -gt 0 -and
            $null -ne (Get-Process -Id $runtimePid -ErrorAction SilentlyContinue)) {
            throw 'ARMI-RESET-RUNTIME: stop Runtime before clearing local data.'
        }
    }
    catch [System.Management.Automation.RuntimeException] {
        throw
    }
    catch {
        throw 'ARMI-RESET-DESCRIPTOR: runtime process descriptor is invalid.'
    }
}

$semanticServicePath = Join-Path $root 'run/semantic-recall/service.json'
if (Test-Path -LiteralPath $semanticServicePath -PathType Leaf) {
    try {
        $semanticService = Get-Content -LiteralPath $semanticServicePath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        $semanticPid = [int]$semanticService.pid
        if ($semanticPid -gt 0 -and
            $null -ne (Get-Process -Id $semanticPid -ErrorAction SilentlyContinue)) {
            throw 'ARMI-RESET-SEMANTIC: stop semantic recall before clearing local data.'
        }
    }
    catch [System.Management.Automation.RuntimeException] {
        throw
    }
    catch {
        throw 'ARMI-RESET-SEMANTIC-DESCRIPTOR: semantic service descriptor is invalid.'
    }
}

$relativeTargets = @(
    'data\artifacts',
    'data\backups',
    'data\codex-runner',
    'data\exports',
    'data\logs',
    'run'
)
$results = @()

foreach ($relativeTarget in $relativeTargets) {
    $target = [IO.Path]::GetFullPath((Join-Path $root $relativeTarget))
    if (-not $target.StartsWith($rootBoundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw "ARMI-RESET-BOUNDARY: target escapes environment root: $relativeTarget"
    }

    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType Directory -Path $target | Out-Null
    }
    $targetItem = Get-Item -LiteralPath $target -Force -ErrorAction Stop
    if (-not $targetItem.PSIsContainer -or
        ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "ARMI-RESET-TARGET: target must be a real directory: $relativeTarget"
    }

    $reparsePoints = @(
        Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint
    )
    if ($reparsePoints.Count -ne 0) {
        throw "ARMI-RESET-REPARSE: reparse point found below: $relativeTarget"
    }

    $children = @(Get-ChildItem -LiteralPath $target -Force)
    foreach ($child in $children) {
        if ([IO.Path]::GetDirectoryName($child.FullName) -ne $target) {
            throw "ARMI-RESET-CHILD: unexpected child path below: $relativeTarget"
        }
        Remove-Item -LiteralPath $child.FullName -Recurse -Force -ErrorAction Stop
    }
    if (@(Get-ChildItem -LiteralPath $target -Force).Count -ne 0) {
        throw "ARMI-RESET-NOT-EMPTY: target was not cleared: $relativeTarget"
    }
    $results += [ordered]@{
        path = $relativeTarget.Replace('\', '/')
        removed_children = $children.Count
        status = 'empty'
    }
}

[ordered]@{
    status = 'cleared'
    targets = $results
} | ConvertTo-Json -Depth 4
