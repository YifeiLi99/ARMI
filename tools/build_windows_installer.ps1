[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PayloadDirectory,
    [Parameter(Mandatory)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$payload = [IO.Path]::GetFullPath($PayloadDirectory)
$output = [IO.Path]::GetFullPath($OutputDirectory)
$manifest = Get-Content -LiteralPath (Join-Path $workspace 'tools/toolchain-manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
$inno = @($manifest.tools | Where-Object id -eq 'inno-setup')[0]
$compiler = Join-Path $workspace ('.armi-tools/installs/inno-' + $inno.version + '/ISCC.exe')
if ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant() -ne $inno.compiler_sha256) { throw 'INSTALLER-COMPILER-IDENTITY' }
$python = Join-Path $payload 'runtime/python/python.exe'
& $python -I -B -c 'import sys; from pathlib import Path; from armi_admin.application.distribution import ProgramBundle; p=Path(sys.argv[1]); b=ProgramBundle.read(p); b.verify(p)' $payload
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-PAYLOAD-INTEGRITY' }
$bundle = Get-Content -LiteralPath (Join-Path $payload 'bundle.json') -Raw -Encoding utf8 | ConvertFrom-Json
New-Item -ItemType Directory -Path $output -Force | Out-Null
$inventory = Join-Path $output ('uninstall-' + $bundle.package_id + '.iss')
$directories = [Collections.Generic.HashSet[string]]::new()
$lines = [Collections.Generic.List[string]]::new()
foreach ($relative in @($bundle.files.PSObject.Properties.Name) + @('bundle.json')) {
    $name = $relative.Replace('/', '\')
    $lines.Add('Type: files; Name: "{app}\app\' + $name + '"')
    $parent = Split-Path -Parent $name
    if ($name.EndsWith('.py') -and $parent) {
        $cache = $parent + '\__pycache__'
        if ($directories.Add($cache)) { $lines.Add('Type: files; Name: "{app}\app\' + $cache + '\*.pyc"') }
    }
    while ($parent) {
        [void]$directories.Add($parent)
        $parent = Split-Path -Parent $parent
    }
}
foreach ($directory in ($directories | Sort-Object Length -Descending)) {
    $lines.Add('Type: dirifempty; Name: "{app}\app\' + $directory + '"')
}
$lines.Add('Type: dirifempty; Name: "{app}\app"')
[IO.File]::WriteAllLines($inventory, $lines, [Text.UTF8Encoding]::new($false))
& $compiler --quiet ('/DPayloadRoot=' + $payload) ('/DPackageId=' + $bundle.package_id) ('/DOutputRoot=' + $output) ('/DUninstallInventory=' + $inventory) (Join-Path $PSScriptRoot 'windows/armi.iss')
if ($LASTEXITCODE -ne 0) { throw 'INSTALLER-COMPILE-FAILED' }
$executable = Join-Path $output ('ARMI-Windows-x64-' + $bundle.package_id + '-unsigned.exe')
Write-Output $executable
Get-FileHash -LiteralPath $executable -Algorithm SHA256
