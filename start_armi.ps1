[CmdletBinding()]
param(
    [string]$EnvironmentRoot = $env:ARMI_ENVIRONMENT_ROOT
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'ARMI-START-POWERSHELL: PowerShell 7 or newer is required.'
}
if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'ARMI-START-PLATFORM: only Windows x86_64 is supported.'
}
if ([string]::IsNullOrWhiteSpace($EnvironmentRoot)) {
    throw 'ARMI-START-ENVIRONMENT: pass -EnvironmentRoot or set ARMI_ENVIRONMENT_ROOT.'
}

$workspace = [IO.Path]::GetFullPath($PSScriptRoot)
$resolvedEnvironmentRoot = [IO.Path]::GetFullPath($EnvironmentRoot)
if (-not (Test-Path -LiteralPath $resolvedEnvironmentRoot -PathType Container)) {
    throw "ARMI-START-ENVIRONMENT: environment root does not exist: $resolvedEnvironmentRoot"
}

$managedUv = Join-Path $workspace '.armi-tools/installs/uv/0.11.33/uv.exe'
if (-not (Test-Path -LiteralPath $managedUv -PathType Leaf)) {
    throw 'ARMI-START-TOOLCHAIN: run tools/bootstrap_toolchain.ps1 before starting ARMI.'
}

function Invoke-ArmiJson {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    $raw = @(& $script:armiExecutable @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "ARMI-START-CLI: armi command failed: $($Arguments -join ' ')"
    }
    try {
        return ($raw -join "`n") | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'ARMI-START-CLI: armi command returned invalid JSON.'
    }
}

Push-Location $workspace
try {
    Write-Host 'Synchronizing locked Python dependencies...'
    & $managedUv sync --frozen
    if ($LASTEXITCODE -ne 0) {
        throw 'ARMI-START-SYNC: uv sync failed.'
    }

    $script:armiExecutable = Join-Path $workspace '.venv/Scripts/armi.exe'
    if (-not (Test-Path -LiteralPath $script:armiExecutable -PathType Leaf)) {
        throw 'ARMI-START-CLI: the armi executable is unavailable after uv sync.'
    }

    Write-Host 'Checking the ARMI environment...'
    $config = Invoke-ArmiJson @(
        'config', 'check',
        '--environment-root', $resolvedEnvironmentRoot
    )

    Write-Host 'Starting PostgreSQL...'
    & (Join-Path $workspace 'tools/manage_postgresql.ps1') Start

    Write-Host 'Checking the ARMI database...'
    $null = Invoke-ArmiJson @(
        'db', 'status',
        '--environment-root', $resolvedEnvironmentRoot
    )

    Write-Host 'Starting the ARMI Runtime...'
    $null = Invoke-ArmiJson @(
        'start',
        '--environment-root', $resolvedEnvironmentRoot
    )
    $status = Invoke-ArmiJson @(
        'status',
        '--environment-root', $resolvedEnvironmentRoot
    )

    if ($status.status -ne 'running') {
        throw "ARMI-START-RUNTIME: expected running, got $($status.status)."
    }
    if ($status.runtime.readiness -ne 'ready') {
        $reasons = @($status.runtime.reason_codes) -join ','
        throw "ARMI-START-READINESS: Runtime is $($status.runtime.runtime_state); reasons=$reasons"
    }

    $creatorUrl = "http://$($config.config.creator.bind_host):$($config.config.creator.port)/ui/"
    [pscustomobject]@{
        status = 'ready'
        environment_root = $resolvedEnvironmentRoot
        runtime_state = $status.runtime.runtime_state
        pid = $status.pid
        creator_url = $creatorUrl
        reason_codes = @($status.runtime.reason_codes)
    }
}
finally {
    Pop-Location
}
