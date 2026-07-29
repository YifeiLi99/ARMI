[CmdletBinding()]
param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ToolRoot,
    [switch]$ApprovedOfficialDirect,
    [switch]$Offline,
    [switch]$PrepareToolsOnly,
    [switch]$SkipBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'S003-POWERSHELL: PowerShell 7 or newer is required.'
}
if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'S003-PLATFORM: only Windows x86_64 is supported.'
}
if ($ApprovedOfficialDirect -and $Offline) {
    throw 'S003-EGRESS: ApprovedOfficialDirect and Offline are mutually exclusive.'
}
if (-not $ApprovedOfficialDirect -and -not $Offline) {
    throw 'S003-EGRESS: online acquisition requires -ApprovedOfficialDirect.'
}

$workspace = [IO.Path]::GetFullPath($WorkspaceRoot)
if (-not (Test-Path -LiteralPath $workspace -PathType Container)) {
    throw "S003-MISSING: workspace does not exist: $WorkspaceRoot"
}
if ([string]::IsNullOrWhiteSpace($ToolRoot)) {
    $ToolRoot = Join-Path $workspace '.armi-tools'
}
$tools = [IO.Path]::GetFullPath($ToolRoot)

if ($ApprovedOfficialDirect) {
    $env:HTTP_PROXY = $null
    $env:HTTPS_PROXY = $null
    $env:ALL_PROXY = $null
    $env:http_proxy = $null
    $env:https_proxy = $null
    $env:all_proxy = $null
}

$manifestPath = Join-Path $workspace 'tools/toolchain-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw 'S003-MISSING: tools/toolchain-manifest.json is missing.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json

function Get-ToolSpec([string]$Id) {
    $spec = $manifest.tools | Where-Object id -eq $Id | Select-Object -First 1
    if ($null -eq $spec) {
        throw "S003-METADATA: tool manifest does not contain $Id."
    }
    return $spec
}

function Get-LowerSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-Artifact([object]$Spec, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        $actual = Get-LowerSha256 $Destination
        if ($actual -ne [string]$Spec.archive_sha256) {
            throw "S003-DIGEST: cached $($Spec.id) archive digest mismatch."
        }
        return
    }
    if ($Offline) {
        throw "S003-OFFLINE-CACHE: $($Spec.id) archive is not cached."
    }
    $parent = Split-Path -Parent $Destination
    [void](New-Item -ItemType Directory -Path $parent -Force)
    Invoke-WebRequest -Uri ([string]$Spec.archive_url) -OutFile $Destination
    $actual = Get-LowerSha256 $Destination
    if ($actual -ne [string]$Spec.archive_sha256) {
        throw "S003-DIGEST: downloaded $($Spec.id) archive digest mismatch."
    }
}

[void](New-Item -ItemType Directory -Path $tools -Force)
$artifactCache = Join-Path $tools 'cache/artifacts'
$uvCache = Join-Path $tools 'cache/uv'
$npmCache = Join-Path $tools 'cache/npm'
$pythonInstallRoot = Join-Path $tools 'installs/python'
$browserRoot = Join-Path $tools 'installs/playwright'
[void](New-Item -ItemType Directory -Path $artifactCache -Force)
[void](New-Item -ItemType Directory -Path $uvCache -Force)
[void](New-Item -ItemType Directory -Path $npmCache -Force)

$uvSpec = Get-ToolSpec 'uv'
$uvArchive = Join-Path $artifactCache 'uv-0.11.33-py3-none-win_amd64.whl'
Get-Artifact $uvSpec $uvArchive
$uvInstall = Join-Path $tools 'installs/uv/0.11.33'
$uvExe = Join-Path $uvInstall 'uv.exe'
if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    [void](New-Item -ItemType Directory -Path $uvInstall -Force)
    $extracted = Join-Path $uvInstall 'wheel'
    [void](New-Item -ItemType Directory -Path $extracted -Force)
    [IO.Compression.ZipFile]::ExtractToDirectory($uvArchive, $extracted, $true)
    $candidate = Get-ChildItem -LiteralPath $extracted -Recurse -File -Filter 'uv.exe' |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw 'S003-MISSING: uv.exe was not found in the pinned wheel.'
    }
    Copy-Item -LiteralPath $candidate.FullName -Destination $uvExe
}
$uvVersion = (& $uvExe --version 2>&1 | Out-String).Trim()
if ($uvVersion -notmatch '^uv 0\.11\.33(?:\s|$)') {
    throw "S003-VERSION: expected uv 0.11.33, got $uvVersion."
}

$nodeSpec = Get-ToolSpec 'node'
$nodeArchive = Join-Path $artifactCache 'node-v24.18.0-win-x64.zip'
Get-Artifact $nodeSpec $nodeArchive
$nodeParent = Join-Path $tools 'installs/node'
$nodeDir = Join-Path $nodeParent 'node-v24.18.0-win-x64'
$nodeExe = Join-Path $nodeDir 'node.exe'
if (-not (Test-Path -LiteralPath $nodeExe -PathType Leaf)) {
    [void](New-Item -ItemType Directory -Path $nodeParent -Force)
    [IO.Compression.ZipFile]::ExtractToDirectory($nodeArchive, $nodeParent, $true)
}
$npmCmd = Join-Path $nodeDir 'npm.cmd'
if (-not (Test-Path -LiteralPath $npmCmd -PathType Leaf)) {
    throw 'S003-MISSING: pinned Node archive does not contain npm.cmd.'
}
$nodeVersion = (& $nodeExe --version 2>&1 | Out-String).Trim().TrimStart('v')
$oldPath = $env:PATH
$env:PATH = "$nodeDir;$oldPath"
$npmVersion = (& $npmCmd --version 2>&1 | Out-String).Trim()
if ($nodeVersion -ne '24.18.0') {
    throw "S003-VERSION: expected Node 24.18.0, got $nodeVersion."
}
if ($npmVersion -ne '11.16.0') {
    throw "S003-VERSION: expected npm 11.16.0, got $npmVersion."
}

$env:UV_CACHE_DIR = $uvCache
$env:UV_PYTHON_INSTALL_DIR = $pythonInstallRoot
$pythonExe = $null
try {
    $pythonExe = (& $uvExe python find 3.14.6 --managed-python 2>$null | Select-Object -First 1)
} catch {
    $pythonExe = $null
}
if ([string]::IsNullOrWhiteSpace([string]$pythonExe) -or -not (Test-Path -LiteralPath $pythonExe)) {
    if ($Offline) {
        throw 'S003-OFFLINE-CACHE: CPython 3.14.6 is not present in the isolated tool root.'
    }
    & $uvExe python install 3.14.6 --no-bin
    if ($LASTEXITCODE -ne 0) {
        throw 'S003-INSTALL: CPython 3.14.6 installation failed.'
    }
    $pythonExe = (& $uvExe python find 3.14.6 --managed-python | Select-Object -First 1)
}
$pythonVersion = (& $pythonExe --version 2>&1 | Out-String).Trim()
if ($pythonVersion -ne 'Python 3.14.6') {
    throw "S003-VERSION: expected Python 3.14.6, got $pythonVersion."
}

if (-not $PrepareToolsOnly) {
    $uvArguments = @('sync', '--locked', '--all-packages', '--managed-python', '--python', $pythonExe)
    if ($Offline) {
        $uvArguments += '--offline'
    }
    & $uvExe @uvArguments --project $workspace
    if ($LASTEXITCODE -ne 0) {
        throw 'S003-INSTALL: uv sync from the lockfile failed.'
    }

    $env:NPM_CONFIG_CACHE = $npmCache
    $npmArguments = @('ci', '--no-audit', '--no-fund')
    if ($Offline) {
        $npmArguments += '--offline'
    }
    foreach ($relative in @('apps/armi-creator-web', 'tools/toolchain-node')) {
        Push-Location (Join-Path $workspace $relative)
        try {
            & $npmCmd @npmArguments
            if ($LASTEXITCODE -ne 0) {
                throw "S003-INSTALL: npm ci failed for $relative."
            }
        } finally {
            Pop-Location
        }
    }

    if (-not $SkipBrowser) {
        $env:PLAYWRIGHT_BROWSERS_PATH = $browserRoot
        $chromiumExists = @(
            Get-ChildItem -LiteralPath $browserRoot -Recurse -File -Filter 'chrome.exe' -ErrorAction SilentlyContinue
        ).Count -gt 0
        if (-not $chromiumExists) {
            if ($Offline) {
                throw 'S003-OFFLINE-CACHE: Playwright Chromium is not present in the isolated tool root.'
            }
            $workspacePython = Join-Path $workspace '.venv/Scripts/python.exe'
            & $workspacePython -m playwright install chromium
            if ($LASTEXITCODE -ne 0) {
                throw 'S003-INSTALL: Playwright Chromium installation failed.'
            }
        }
    }
}

[pscustomobject]@{
    status = 'pass'
    python = $pythonVersion
    uv = $uvVersion
    node = $nodeVersion
    npm = $npmVersion
    mode = if ($Offline) { 'offline' } else { 'approved_official_direct' }
    prepared_only = [bool]$PrepareToolsOnly
} | Format-List
