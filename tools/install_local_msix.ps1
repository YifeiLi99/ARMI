[CmdletBinding()]
param(
    [string]$CertificateThumbprint,
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7 -or -not $IsWindows) {
    throw 'LOCAL-MSIX-PLATFORM: run with PowerShell 7 on Windows.'
}
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$packageName = 'YifeiLi99.ARMI.Acceptance'
$dataRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ARMI.Acceptance'
$outputRoot = Join-Path $workspace 'dist/msix-local'
$scratchRoot = Join-Path $workspace '.tmp'
New-Item -ItemType Directory -Path $scratchRoot -Force | Out-Null
# Serialize version allocation and builds in this checkout; never reuse an old payload.
$lock = [IO.File]::Open((Join-Path $scratchRoot 'local-msix.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
Push-Location $workspace
try {
    $installed = Get-AppxPackage -Name $packageName
    $publisher = if ($installed) { $installed.Publisher } else { 'CN=ARMI MSIX Acceptance' }
    if ($CertificateThumbprint) {
        if ($CertificateThumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'LOCAL-MSIX-CERTIFICATE: invalid thumbprint.' }
        $certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $CertificateThumbprint)
    } else {
        $certificates = @(Get-ChildItem Cert:\CurrentUser\My | Where-Object {
            $_.Subject -eq $publisher -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date)
        })
        if ($certificates.Count -ne 1) {
            throw 'LOCAL-MSIX-CERTIFICATE: supply -CertificateThumbprint for a valid acceptance signing certificate in CurrentUser\My.'
        }
        $certificate = $certificates[0]
    }
    if ($certificate.Subject -ne $publisher -or -not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date)) {
        throw 'LOCAL-MSIX-CERTIFICATE: publisher, private key or validity does not match this acceptance installation.'
    }
    # Trust provisioning is separate from building. This command never imports certificates.
    $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
    try {
        $chain.ChainPolicy.RevocationMode = 'NoCheck'
        $directTrust = Test-Path -LiteralPath ("Cert:\LocalMachine\TrustedPeople\" + $certificate.Thumbprint)
        if (-not $directTrust -and -not $chain.Build($certificate)) {
            throw 'LOCAL-MSIX-TRUST: trust the public acceptance certificate on this test computer before building.'
        }
    } finally { $chain.Dispose() }

    $python = Join-Path $workspace '.venv/Scripts/python.exe'
    $releasePath = Join-Path $workspace 'configs/windows-release.yaml'
    $releaseVersion = & $python -I -B -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1],encoding="utf-8"))["version"])' $releasePath
    if ($LASTEXITCODE -ne 0) { throw 'LOCAL-MSIX-RELEASE-CONFIGURATION' }
    $highest = [version]$releaseVersion
    if ($installed -and [version]$installed.Version -gt $highest) { $highest = [version]$installed.Version }
    if (Test-Path -LiteralPath $outputRoot) {
        foreach ($directory in Get-ChildItem -LiteralPath $outputRoot -Directory) {
            if ($directory.Name -match '^\d+\.\d+\.\d+\.\d+$' -and [version]$directory.Name -gt $highest) {
                $highest = [version]$directory.Name
            }
        }
    }
    $parts = @($highest.Major, $highest.Minor, $highest.Build, $highest.Revision)
    for ($index = 3; $index -ge 0; $index--) {
        if ($parts[$index] -lt 65535) { $parts[$index]++; break }
        $parts[$index] = 0
    }
    if ($index -lt 0) { throw 'LOCAL-MSIX-VERSION-EXHAUSTED' }
    $version = $parts -join '.'
    $work = Join-Path $scratchRoot ('local-msix-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    $localRelease = Join-Path $work 'windows-release.yaml'
    & $python -I -B -c 'import sys,yaml; from pathlib import Path; v=yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")); v["version"]=sys.argv[3]; Path(sys.argv[2]).write_text(yaml.safe_dump(v,allow_unicode=True,sort_keys=False),encoding="utf-8")' $releasePath $localRelease $version
    if ($LASTEXITCODE -ne 0) { throw 'LOCAL-MSIX-RELEASE-CONFIGURATION' }
    $payload = Join-Path $work 'payload'
    $output = Join-Path $outputRoot $version
    Write-Host "Building current source as $packageName $version ..."
    Write-Host "Build logs: $work"
    & (Join-Path $PSScriptRoot 'build_windows_payload.ps1') -OutputDirectory $payload *> (Join-Path $work 'payload.log')
    if ($LASTEXITCODE -ne 0) { throw "LOCAL-MSIX-PAYLOAD: inspect $work\payload.log" }
    Write-Host 'Payload and native entry-point checks passed; creating signed MSIX ...'
    & (Join-Path $PSScriptRoot 'build_windows_installer.ps1') -PayloadDirectory $payload -OutputDirectory $output -CertificateThumbprint $certificate.Thumbprint -ReleaseConfiguration $localRelease -Development *> (Join-Path $work 'package.log')
    if ($LASTEXITCODE -ne 0) { throw "LOCAL-MSIX-PACK: inspect $work\package.log" }
    $package = Join-Path $output ($packageName + '-' + $version + '-x64.msix')
    if ($BuildOnly) { Write-Output $package; return }

    # Use only registered acceptance environments and the existing Admin stop use case.
    # Validate the signed build's database contract before disturbing a running instance.
    $indexPath = Join-Path $dataRoot 'control/environments.yaml'
    $environments = @()
    if (Test-Path -LiteralPath $indexPath) {
        $registration = Get-Content -LiteralPath $indexPath -Raw -Encoding utf8 | ConvertFrom-Json
        if ($registration.schema_version -ne 'armi.installation-environments.v2' -or [IO.Path]::GetFullPath($registration.installation_root) -ne $dataRoot) {
            throw 'LOCAL-MSIX-ENVIRONMENT-REGISTRATION'
        }
        $environments = @($registration.environments)
        $bundle = Get-Content -LiteralPath (Join-Path $output 'staging/bundle.json') -Raw -Encoding utf8 | ConvertFrom-Json
        foreach ($environment in $environments) {
            $resolved = [IO.Path]::GetFullPath($environment)
            if ([IO.Path]::GetDirectoryName($resolved) -ne (Join-Path $dataRoot 'environments')) { throw 'LOCAL-MSIX-ENVIRONMENT-BOUNDARY' }
            $binding = Get-Content -LiteralPath (Join-Path $resolved '.setup/program.json') -Raw -Encoding utf8 | ConvertFrom-Json
            foreach ($field in @('postgresql', 'vector', 'pg_trgm', 'baseline', 'schema_digest', 'role_policy_digest')) {
                if ($binding.database.$field -ne $bundle.database.$field) {
                    throw "LOCAL-MSIX-DATABASE-INCOMPATIBLE: package built at $package; retained data requires a matching database contract."
                }
            }
        }
    }
    $alias = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Microsoft/WindowsApps/ARMI.Acceptance.exe'
    if ($installed) {
        foreach ($environment in $environments) {
            $request = @{action='admin'; operation='environment_stop'; arguments=@{idempotency_key=[Guid]::NewGuid().ToString()}} | ConvertTo-Json -Compress
            $result = $request | & $alias cli setup --environment-root $environment | ConvertFrom-Json
            if ($LASTEXITCODE -ne 0 -or $result.status -ne 'succeeded') {
                throw "LOCAL-MSIX-STOP-UNCONFIRMED: $($result.error_code); update was not requested."
            }
        }
    }
    Write-Host "Installing $version with Windows package management ..."
    Add-AppxPackage -Path $package -ForceTargetApplicationShutdown
    $actual = Get-AppxPackage -Name $packageName
    if (-not $actual -or [version]$actual.Version -ne [version]$version) { throw 'LOCAL-MSIX-DEPLOYMENT-NOT-CONFIRMED' }
    # Local development does not contact GitHub. Preserve this preference across updates.
    $setting = '{"action":"update","update":{"action":"automatic","enabled":false}}' | & $alias cli setup | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $setting.automatic -ne $false) { throw 'LOCAL-MSIX-AUTOMATIC-SETTING-FAILED' }
    Write-Output "Installed $($actual.PackageFullName). Environment remains stopped; automatic GitHub updates are disabled."
    Write-Output "Package: $package"
    Write-Output "Run: & '$alias'"
} finally {
    Pop-Location
    $lock.Dispose()
}
