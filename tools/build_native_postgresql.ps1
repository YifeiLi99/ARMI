[CmdletBinding()]
param(
    [string]$ToolRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) '.armi-tools'),
    [string]$VisualStudioRoot = '',
    [switch]$ApprovedOfficialDirect
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$toolDirectory = [IO.Path]::GetFullPath($ToolRoot)
$manifest = Get-Content -LiteralPath (Join-Path $workspace 'tools/toolchain-manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
$spec = $manifest.tools | Where-Object id -eq 'pgvector-windows'
if ($null -eq $spec) { throw 'PG-NATIVE-MANIFEST: pgvector specification is missing' }
$cache = Join-Path $toolDirectory 'cache/native-installer'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
$archive = Join-Path $cache 'pgvector-0.8.6.zip'
if (-not (Test-Path -LiteralPath $archive)) {
    if (-not $ApprovedOfficialDirect) { throw 'PG-NATIVE-CACHE: exact source archive is missing' }
    Invoke-WebRequest -NoProxy -Uri $spec.archive_url -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive).Hash.ToLowerInvariant() -ne $spec.archive_sha256) {
    throw 'PG-NATIVE-SOURCE-HASH: pgvector archive does not match'
}
if ([string]::IsNullOrWhiteSpace($VisualStudioRoot)) {
    $VisualStudioRoot = Join-Path $toolDirectory 'installs/msvc'
}
$vcvars = Join-Path $VisualStudioRoot 'VC/Auxiliary/Build/vcvars64.bat'
if (-not (Test-Path -LiteralPath $vcvars)) { throw 'PG-NATIVE-COMPILER: MSVC x64 build tools are required on the build machine' }
$compilerSpec = $manifest.tools | Where-Object id -eq 'msvc-build-tools'
$compilerVersion = (Get-Content -LiteralPath (Join-Path $VisualStudioRoot 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
if ($compilerVersion -ne $compilerSpec.toolset_version) { throw 'PG-NATIVE-COMPILER-VERSION: use the locked MSVC toolset' }
$original = Join-Path $toolDirectory 'installs/postgresql/18.4/pgsql'
if (-not (Test-Path -LiteralPath (Join-Path $original 'bin/postgres.exe'))) {
    throw 'PG-NATIVE-POSTGRES: prepare the locked PostgreSQL archive first'
}
$destination = Join-Path $toolDirectory 'installs/postgresql-native/18.4-vector-0.8.6-utf8/pgsql'
if (Test-Path -LiteralPath $destination) { throw 'PG-NATIVE-EXISTS: use the existing distribution or an empty tool root' }
$stage = Join-Path $toolDirectory ('staging/native-pg-' + [Guid]::NewGuid().ToString('N'))
$pgstage = Join-Path $stage 'pgsql'
New-Item -ItemType Directory -Path $pgstage -Force | Out-Null
foreach ($part in @('bin', 'lib', 'share', 'include')) {
    Copy-Item -LiteralPath (Join-Path $original $part) -Destination $pgstage -Recurse
}
Get-ChildItem -LiteralPath $original -File | Where-Object Name -Match 'license|copyright' | Copy-Item -Destination $pgstage
Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $stage 'source')
$source = Join-Path $stage 'source/pgvector-0.8.6'
$previousPgRoot = $env:PGROOT
try {
    $env:PGROOT = $pgstage
    Push-Location -LiteralPath $source
    try {
        & $env:ComSpec /d /s /c "`"call `"$vcvars`" && nmake /NOLOGO /F Makefile.win && nmake /NOLOGO /F Makefile.win install`""
        if ($LASTEXITCODE -ne 0) { throw 'PG-NATIVE-BUILD: pgvector compilation failed' }
    } finally { Pop-Location }
} finally { $env:PGROOT = $previousPgRoot }
Copy-Item -LiteralPath (Join-Path $source 'LICENSE') -Destination (Join-Path $pgstage 'pgvector-LICENSE')
$utf8Manifest = Join-Path $workspace 'tools/windows/utf8.manifest'
$manifestTool = Join-Path ${env:ProgramFiles(x86)} ('Windows Kits/10/bin/' + $compilerSpec.windows_sdk_version + '/x64/mt.exe')
if (-not (Test-Path -LiteralPath $manifestTool)) { throw 'PG-NATIVE-SDK: locked Windows SDK manifest tool is missing' }
# These exact vendor executables have no embedded application manifest. A
# process-local UTF-8 code page makes non-ASCII installation paths valid in
# initdb's bootstrap SQL without changing the user's Windows locale.
foreach ($name in @('postgres', 'initdb', 'pg_ctl', 'pg_controldata', 'pg_isready', 'psql')) {
    $executable = Join-Path $pgstage ('bin/' + $name + '.exe')
    & $manifestTool -nologo -manifest $utf8Manifest ('-outputresource:' + $executable + ';#1')
    if ($LASTEXITCODE -ne 0) { throw 'PG-NATIVE-UTF8-MANIFEST: embedding failed' }
}
Copy-Item -LiteralPath $utf8Manifest -Destination (Join-Path $pgstage 'armi-process-utf8.manifest')
$inventory = [ordered]@{}
Get-ChildItem -LiteralPath $pgstage -Recurse -File | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($pgstage, $_.FullName).Replace('\', '/')
    $inventory[$relative] = (Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant()
}
$record = [ordered]@{schema_version='armi.native-postgresql-distribution.v1'; postgresql='18.4'; vector='0.8.6'; pg_trgm='1.6'; process_code_page='UTF-8'; compiler=$compilerVersion; source_sha256=$spec.archive_sha256; files=$inventory}
[IO.File]::WriteAllText((Join-Path $pgstage 'distribution.json'), (($record | ConvertTo-Json -Depth 5) + "`n"), [Text.UTF8Encoding]::new($false))
New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
Move-Item -LiteralPath $pgstage -Destination $destination
Write-Output "Native PostgreSQL distribution: $destination"
