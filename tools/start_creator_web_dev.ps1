[CmdletBinding()]
param(
    [string]$EnvironmentRoot = $env:ARMI_ENVIRONMENT_ROOT,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'ARMI-WEB-DEV-POWERSHELL: PowerShell 7 or newer is required.'
}

$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($EnvironmentRoot)) {
    $EnvironmentRoot = Join-Path (Split-Path -Parent $workspace) 'ARMI-Environment'
}
$resolvedEnvironmentRoot = [IO.Path]::GetFullPath($EnvironmentRoot)
$armiExecutable = Join-Path $workspace '.venv/Scripts/armi.exe'
$node = Join-Path $workspace '.armi-tools/installs/node/node-v24.18.0-win-x64/node.exe'
$vite = Join-Path $workspace 'apps/armi-creator-web/node_modules/vite/bin/vite.js'
foreach ($path in @($armiExecutable, $node, $vite)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "ARMI-WEB-DEV-TOOLCHAIN: required tool is unavailable: $path"
    }
}

function Invoke-ArmiJson {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $raw = @(& $script:armiExecutable @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "ARMI-WEB-DEV-CLI: armi command failed: $($Arguments -join ' ')"
    }
    return ($raw -join "`n") | ConvertFrom-Json -ErrorAction Stop
}

$script:armiExecutable = $armiExecutable
$config = Invoke-ArmiJson @('config', 'check', '--environment-root', $resolvedEnvironmentRoot)
$status = Invoke-ArmiJson @('status', '--environment-root', $resolvedEnvironmentRoot)
if ($status.status -ne 'running' -or $status.runtime.readiness -ne 'ready') {
    throw 'ARMI-WEB-DEV-RUNTIME: start a ready Runtime with start_armi.ps1 first.'
}

$runtimeOrigin = "http://$($config.config.creator.bind_host):$($config.config.creator.port)"
$previousOrigin = $env:ARMI_CREATOR_RUNTIME_ORIGIN
$env:ARMI_CREATOR_RUNTIME_ORIGIN = $runtimeOrigin
Push-Location (Join-Path $workspace 'apps/armi-creator-web')
try {
    $arguments = @($vite, '--host', '127.0.0.1', '--port', '5173', '--strictPort')
    if ($OpenBrowser) {
        $arguments += @('--open', '/ui/')
    }
    & $node @arguments
    $viteExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    $env:ARMI_CREATOR_RUNTIME_ORIGIN = $previousOrigin
}
if ($viteExitCode -ne 0) {
    throw "ARMI-WEB-DEV-VITE: Vite exited with code $viteExitCode."
}
