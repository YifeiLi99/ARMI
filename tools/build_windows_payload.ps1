[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$OutputDirectory,
    [switch]$ApprovedOfficialDirect
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'INSTALLER-OUTPUT-EXISTS: select a new staging directory' }
$tools = Join-Path $workspace '.armi-tools'
$pythonSource = Join-Path $tools 'installs/python/cpython-3.14.6-windows-x86_64-none'
$pgSource = Join-Path $tools 'installs/postgresql-native/18.4-vector-0.8.6-utf8/pgsql'
$uv = Join-Path $tools 'installs/uv/0.11.33/uv.exe'
if (-not (Test-Path -LiteralPath (Join-Path $pgSource 'distribution.json'))) {
    throw 'INSTALLER-POSTGRESQL-MISSING: build the native distribution first'
}
& (Join-Path $PSScriptRoot 'quality.ps1') -Gate BUILD-WEB,BUILD-PY
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-WHEEL-BUILD' }
New-Item -ItemType Directory -Path (Join-Path $output 'runtime') -Force | Out-Null
Copy-Item -LiteralPath $pythonSource -Destination (Join-Path $output 'runtime/python') -Recurse
# The copied interpreter is owned by the ARMI payload builder, not uv's tool store.
Remove-Item -LiteralPath (Join-Path $output 'runtime/python/Lib/EXTERNALLY-MANAGED') -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $output 'postgresql') | Out-Null
Copy-Item -LiteralPath $pgSource -Destination (Join-Path $output 'postgresql/pgsql') -Recurse
$python = Join-Path $output 'runtime/python/python.exe'
$requirements = Join-Path $output 'locked-dependencies.txt'
$previousCache = $env:UV_CACHE_DIR
$previousNoManaged = $env:UV_PYTHON_DOWNLOADS
try {
    $env:UV_CACHE_DIR = Join-Path $tools 'cache/uv'
    $env:UV_PYTHON_DOWNLOADS = 'never'
    [string[]]$network = @()
    if (-not $ApprovedOfficialDirect) { $network += '--offline' }
    & $uv export --project $workspace --locked --all-packages --no-dev --no-editable --no-emit-workspace --output-file $requirements @network 1>$null
    if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-DEPENDENCY-EXPORT' }
    & $uv pip install --python $python --require-hashes --only-binary ':all:' --requirements $requirements @network
    if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-DEPENDENCIES: exact wheel archives are required' }
    $wheels = @(Get-ChildItem -LiteralPath (Join-Path $workspace '.tmp/quality/python-dist') -Filter '*.whl' -File | ForEach-Object FullName)
    & $uv pip install --python $python --no-deps --offline @wheels
    if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-WORKSPACE-WHEELS' }
} finally {
    $env:UV_CACHE_DIR = $previousCache
    $env:UV_PYTHON_DOWNLOADS = $previousNoManaged
}
$resources = Join-Path $output 'resources'
New-Item -ItemType Directory -Path $resources | Out-Null
$runtimePackage = Join-Path $output 'runtime/python/Lib/site-packages/armi_runtime'
Copy-Item -LiteralPath (Join-Path $runtimePackage 'composition/runtime_resources/runtime.yaml') -Destination $resources
Copy-Item -LiteralPath (Join-Path $runtimePackage 'interfaces/creator_web_resources') -Destination (Join-Path $resources 'creator-web') -Recurse
$vcvars = Join-Path $tools 'installs/msvc/VC/Auxiliary/Build/vcvars64.bat'
if (-not (Test-Path -LiteralPath $vcvars)) { throw 'INSTALLER-COMPILER: locked MSVC is required on the build machine' }
$launcherSource = Join-Path $workspace 'tools/windows/launcher.c'
$objects = Join-Path $workspace ('.tmp/quality/windows-launcher-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $objects | Out-Null
& $env:ComSpec /d /s /c "`"call `"$vcvars`" && cl /nologo /W4 /WX /O2 /MT /Brepro /DARMI_GUI `"$launcherSource`" /Fo`"$objects\desktop.obj`" /Fe`"$output\ARMI.exe`" /link /Brepro /SUBSYSTEM:WINDOWS shell32.lib user32.lib`""
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-DESKTOP-LAUNCHER' }
& $python -I -B (Join-Path $workspace 'tools/seal_windows_payload.py') $output
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-SEAL' }
# Verify that the installed package closure is sealed and no developer venv is used.
& $python -I -B -m armi_admin.cli identity
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-PACKAGE-IDENTITY' }
& $python -I -B -c 'import tkinter; assert tkinter.Tcl().eval("info patchlevel").startswith("8.6.")'
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-TK-RUNTIME' }
& $python -B (Join-Path $workspace 'tools/verify_windows_entrypoint.py') $output
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-ENTRYPOINT-VERIFICATION' }
Write-Output "Windows payload prepared: $output"
