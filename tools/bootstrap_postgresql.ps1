[CmdletBinding()]
param(
    [Parameter()]
    [string]$ToolRoot = '.armi-tools',

    [Parameter()]
    [switch]$AllowOfficialNetwork
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$archiveUrl = 'https://get.enterprisedb.com/postgresql/postgresql-18.4-1-windows-x64-binaries.zip'
$expectedArchiveSha = '7effe34c0bf89027b3f171447d351cbc460f4566c8d0f643daec67f140787858'
$expectedInstallSha = '0205691fc599bc780d55e653edbf7085fa5474f3eb6d6b8227bd60b3a8ba4a9f'
$toolRootPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..' $ToolRoot))
$cacheRoot = Join-Path $toolRootPath 'cache/postgresql'
$installRoot = Join-Path $toolRootPath 'installs/postgresql/18.4'
$archivePath = Join-Path $cacheRoot 'postgresql-18.4-1-windows-x64-binaries.zip'
$psqlPath = Join-Path $installRoot 'pgsql/bin/psql.exe'

New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    if (-not $AllowOfficialNetwork) {
        throw 'PG-CACHE-INCOMPLETE: the exact PostgreSQL archive is not cached'
    }
    $proxyNames = @(
        'ALL_PROXY', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
        'all_proxy', 'http_proxy', 'https_proxy', 'no_proxy'
    )
    $savedProxy = @{}
    try {
        foreach ($name in $proxyNames) {
            $savedProxy[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
        Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing
    }
    finally {
        foreach ($name in $proxyNames) {
            [Environment]::SetEnvironmentVariable($name, $savedProxy[$name], 'Process')
        }
    }
}

$archiveSha = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($archiveSha -ne $expectedArchiveSha) {
    throw 'PG-ARCHIVE-HASH: cached PostgreSQL archive digest does not match'
}
if (-not (Test-Path -LiteralPath $psqlPath -PathType Leaf)) {
    $stagingRoot = Join-Path $toolRootPath 'staging/postgresql-18.4'
    $resolvedStaging = [System.IO.Path]::GetFullPath($stagingRoot)
    $resolvedToolRoot = [System.IO.Path]::GetFullPath($toolRootPath)
    if (-not $resolvedStaging.StartsWith($resolvedToolRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'PG-TOOL-ROOT: extraction staging escaped the isolated tool root'
    }
    if (Test-Path -LiteralPath $resolvedStaging) {
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolvedStaging -Force | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $resolvedStaging
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedStaging 'pgsql/bin/psql.exe'))) {
        throw 'PG-ARCHIVE-LAYOUT: official archive layout is unexpected'
    }
    $resolvedInstall = [System.IO.Path]::GetFullPath($installRoot)
    if (-not $resolvedInstall.StartsWith($resolvedToolRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'PG-TOOL-ROOT: install target escaped the isolated tool root'
    }
    if (Test-Path -LiteralPath $resolvedInstall) {
        Remove-Item -LiteralPath $resolvedInstall -Recurse -Force
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedInstall) -Force | Out-Null
    Move-Item -LiteralPath $resolvedStaging -Destination $resolvedInstall
}

$version = (& $psqlPath --version 2>$null)
if ($LASTEXITCODE -ne 0 -or $version -ne 'psql (PostgreSQL) 18.4') {
    throw 'PG-VERSION: isolated PostgreSQL must be exactly 18.4'
}
if (-not (Test-Path -LiteralPath (Join-Path $installRoot 'pgsql/share/timezonesets') -PathType Container)) {
    throw 'PG-INSTALL-INCOMPLETE: isolated PostgreSQL share resources are missing'
}

$digestBuilder = [Text.StringBuilder]::new()
$installFiles = Get-ChildItem -LiteralPath $installRoot -File -Recurse
$relativeFiles = @(
    $installFiles | ForEach-Object {
        [pscustomobject]@{
            Relative = [System.IO.Path]::GetRelativePath($installRoot, $_.FullName).Replace('\', '/')
            FullName = $_.FullName
        }
    }
)
[Array]::Sort(
    $relativeFiles,
    [System.Collections.Generic.Comparer[object]]::Create(
        { param($left, $right) [StringComparer]::Ordinal.Compare($left.Relative, $right.Relative) }
    )
)
foreach ($file in $relativeFiles) {
    $sha = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    [void]$digestBuilder.Append($file.Relative).Append("`t").Append($sha).Append("`n")
}
$installSha = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($digestBuilder.ToString())
    )
).ToLowerInvariant()
if ($installSha -ne $expectedInstallSha) {
    throw 'PG-INSTALL-HASH: isolated PostgreSQL installation digest does not match'
}

[pscustomobject]@{
    status = 'pass'
    version = '18.4'
    archive_sha256 = $archiveSha
    install_sha256 = $installSha
    file_count = $relativeFiles.Count
    network_used = $AllowOfficialNetwork.IsPresent
}
