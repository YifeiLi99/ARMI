[CmdletBinding()]
param(
    [string]$ToolRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) '.armi-tools'),
    [switch]$ApprovedOfficialDirect
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$tools = [IO.Path]::GetFullPath($ToolRoot)
$manifest = Get-Content -LiteralPath (Join-Path $workspace 'tools/toolchain-manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
$cache = Join-Path $tools 'cache/native-installer'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
foreach ($id in @('msvc-build-tools', 'inno-setup')) {
    $spec = @($manifest.tools | Where-Object id -eq $id)[0]
    $fileName = if ($id -eq 'msvc-build-tools') { 'vs_BuildTools.exe' } else { 'innosetup-' + $spec.version + '-x64.exe' }
    $archive = Join-Path $cache $fileName
    if (-not (Test-Path -LiteralPath $archive)) {
        if (-not $ApprovedOfficialDirect) { throw "INSTALLER-TOOL-CACHE: $id requires its exact installer" }
        Invoke-WebRequest -NoProxy -Uri $spec.archive_url -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.archive_sha256) {
        throw "INSTALLER-TOOL-HASH: $id"
    }
    if ($id -eq 'msvc-build-tools') {
        $destination = Join-Path $tools 'installs/msvc'
        $versionFile = Join-Path $destination 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        if (-not (Test-Path -LiteralPath $versionFile)) {
            if (-not $ApprovedOfficialDirect) { throw 'INSTALLER-MSVC-NETWORK: MSVC setup requires authorized downloads and Windows administrator confirmation' }
            $arguments = '--quiet --wait --norestart --installPath "' + $destination + '" --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.26100'
            $result = Start-Process -FilePath $archive -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
            if ($result.ExitCode -notin @(0, 3010)) { throw "INSTALLER-MSVC-INSTALL: exit $($result.ExitCode)" }
        }
        if ((Get-Content -LiteralPath $versionFile -Raw).Trim() -ne $spec.toolset_version) { throw 'INSTALLER-MSVC-VERSION' }
    } else {
        $destination = Join-Path $tools ('installs/inno-' + $spec.version)
        $compiler = Join-Path $destination 'ISCC.exe'
        if (-not (Test-Path -LiteralPath $compiler)) {
            $arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="' + $destination + '"'
            $result = Start-Process -FilePath $archive -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
            if ($result.ExitCode -ne 0) { throw "INSTALLER-INNO-INSTALL: exit $($result.ExitCode)" }
        }
        if ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.compiler_sha256) { throw 'INSTALLER-INNO-VERSION' }
    }
    Write-Output "$id ready"
}
