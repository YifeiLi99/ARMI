[CmdletBinding()]
param(
    [string]$EnvironmentRoot = $env:ARMI_ENVIRONMENT_ROOT,
    [string]$AdminConfig = $env:ARMI_ADMIN_CONFIG,
    [string]$AdminExecutable,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'ARMI-WEB-DEV-POWERSHELL: PowerShell 7 or newer is required.'
}

$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($AdminConfig)) {
    throw 'ARMI-WEB-DEV-BINDING: specify -AdminConfig or ARMI_ADMIN_CONFIG.'
}
$script:entryArguments = @()
if ([string]::IsNullOrWhiteSpace($AdminExecutable)) {
    $AdminExecutable = Join-Path $workspace '.venv/Scripts/python.exe'
    $script:entryArguments = @('-m', 'armi_app')
}
$adminCommand = Get-Command $AdminExecutable -CommandType Application -ErrorAction Stop
$armiExecutable = $adminCommand.Source
$node = Join-Path $workspace '.armi-tools/installs/node/node-v24.18.0-win-x64/node.exe'
$vite = Join-Path $workspace 'apps/armi-creator-web/node_modules/vite/bin/vite.js'
foreach ($path in @($armiExecutable, $node, $vite)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "ARMI-WEB-DEV-TOOLCHAIN: required tool is unavailable: $path"
    }
}

function Invoke-ArmiJson {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $raw = @(& $script:armiExecutable @script:entryArguments cli admin --config $script:AdminConfig @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "ARMI-WEB-DEV-CLI: armi command failed: $($Arguments -join ' ')"
    }
    $response = ($raw -join "`n") | ConvertFrom-Json -ErrorAction Stop
    return $response.result
}

$script:armiExecutable = $armiExecutable
$config = Invoke-ArmiJson @('configuration', '--json', '{"action":"read"}')
$status = Invoke-ArmiJson @('status', '--component', 'runtime')
if (-not [string]::IsNullOrWhiteSpace($EnvironmentRoot)) {
    $expectedDataRoot = [IO.Path]::GetFullPath((Join-Path $EnvironmentRoot 'data'))
    if ($config.effective_on_next_start.environment.data_root -ne $expectedDataRoot) {
        throw 'ARMI-WEB-DEV-ENVIRONMENT: requested root differs from the Admin binding.'
    }
}
if ($status.status -ne 'running' -or $status.runtime.readiness -ne 'ready') {
    throw 'ARMI-WEB-DEV-RUNTIME: start a ready Runtime with start_armi.ps1 first.'
}

$runtimeOrigin = "http://$($config.effective_on_next_start.creator.bind_host):$($config.effective_on_next_start.creator.port)"
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
