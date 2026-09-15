[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PayloadDirectory,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$CertificateThumbprint,
    [string]$ReleaseConfiguration = (Join-Path $PSScriptRoot '../configs/windows-release.yaml'),
    [switch]$Development,
    [switch]$IsolatedAcceptance
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$payload = [IO.Path]::GetFullPath($PayloadDirectory)
$output = [IO.Path]::GetFullPath($OutputDirectory)
$sdk = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64'
if ($CertificateThumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'MSIX-SIGNING-CERTIFICATE-REQUIRED' }
$certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $CertificateThumbprint)
if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date)) { throw 'MSIX-SIGNING-KEY-UNAVAILABLE' }
if (-not $Development -and $certificate.Subject -eq $certificate.Issuer) { throw 'MSIX-PRODUCTION-TRUST-REQUIRED' }
if (Test-Path -LiteralPath $output) { throw 'MSIX-OUTPUT-EXISTS' }
foreach ($managedData in @('environments', 'control', 'cache', 'tmp')) {
    if (Test-Path -LiteralPath (Join-Path $payload $managedData)) { throw 'MSIX-PAYLOAD-CONTAINS-MANAGED-DATA' }
}
$python = Join-Path $payload 'runtime/python/python.exe'
& $python -I -B -c 'import sys; from pathlib import Path; from armi_admin.application.distribution import ProgramBundle; p=Path(sys.argv[1]); ProgramBundle.read(p).verify(p)' $payload
if ($LASTEXITCODE -ne 0) { throw 'MSIX-PAYLOAD-INTEGRITY' }
$staging = Join-Path $output 'staging'
New-Item -ItemType Directory -Path $output | Out-Null
Copy-Item -LiteralPath $payload -Destination $staging -Recurse
& (Join-Path $PSScriptRoot 'build_windows_platform.ps1') -OutputDirectory $staging
$python = Join-Path $staging 'runtime/python/python.exe'
$options = @()
if ($Development) { $options += '--development' }
if ($IsolatedAcceptance) { $options += '--isolated-acceptance' }
$release = & $python -I -B (Join-Path $PSScriptRoot 'prepare_msix_manifest.py') $staging $ReleaseConfiguration $certificate.Subject @options
if ($LASTEXITCODE -ne 0) { throw 'MSIX-RELEASE-CONFIGURATION' }
$release = $release | ConvertFrom-Json
$assets = Join-Path $staging 'Assets'
New-Item -ItemType Directory -Path $assets -Force | Out-Null
foreach ($asset in @('StoreLogo', 'Square44x44Logo', 'Square150x150Logo')) {
    Copy-Item -LiteralPath (Join-Path $staging ('runtime/python/Lib/site-packages/armi_admin/icon_resources/' + $asset + '.png')) -Destination $assets
}
& $python -I -B (Join-Path $PSScriptRoot 'seal_windows_payload.py') $staging
if ($LASTEXITCODE -ne 0) { throw 'MSIX-SEAL' }
$fileName = $release.name + '-' + $release.version + '-x64.msix'
$package = Join-Path $output $fileName
& "$sdk\makeappx.exe" pack /d $staging /p $package /o *> (Join-Path $output 'makeappx.log')
if ($LASTEXITCODE -ne 0) {
    Get-Content -LiteralPath (Join-Path $output 'makeappx.log') -Tail 12
    throw 'MSIX-PACK'
}
& "$sdk\signtool.exe" sign /fd SHA256 /sha1 $CertificateThumbprint $package
if ($LASTEXITCODE -ne 0) { throw 'MSIX-SIGN' }
& "$sdk\signtool.exe" verify /pa $package
if ($LASTEXITCODE -ne 0) { throw 'MSIX-TRUST' }
$bundle = Get-Content -LiteralPath (Join-Path $staging 'bundle.json') -Raw -Encoding utf8 | ConvertFrom-Json
$update = [ordered]@{
    schema_version = 'armi.update.v1'
    name = $release.name
    publisher = $certificate.Subject
    version = $release.version
    architecture = 'x64'
    url = 'https://github.com/' + $release.repository + '/releases/download/' + $release.release_tag + '/' + $fileName
    sha256 = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
    size = (Get-Item -LiteralPath $package).Length
    database = $bundle.database
}
[IO.File]::WriteAllText((Join-Path $output 'armi-update.json'), (($update | ConvertTo-Json -Depth 5) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output $package
