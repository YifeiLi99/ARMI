[CmdletBinding()]
param([Parameter(Mandatory)][string]$OutputDirectory, [switch]$LibraryOnly)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
$objects = Join-Path $workspace ('.tmp/msix-native-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $objects -Force | Out-Null
New-Item -ItemType Directory -Path $output -Force | Out-Null
$vcvars = Join-Path $workspace '.armi-tools/installs/msvc/VC/Auxiliary/Build/vcvars64.bat'
$source = Join-Path $PSScriptRoot 'windows/platform.cpp'
& $env:ComSpec /d /s /c "`"call `"$vcvars`" && cl /nologo /std:c++20 /EHsc /W4 /WX /O2 /MT /LD /Brepro `"$source`" /Fo`"$objects\platform.obj`" /Fe`"$output\armi_windows.dll`" /link /Brepro /IMPLIB:`"$objects\armi_windows.lib`" windowsapp.lib shell32.lib shlwapi.lib ole32.lib wintrust.lib user32.lib`""
if ($LASTEXITCODE -ne 0) { throw 'MSIX-PLATFORM-COMPILE' }
if ($LibraryOnly) { return }
$launcher = Join-Path $PSScriptRoot 'windows/launcher.c'
& $env:ComSpec /d /s /c "`"call `"$vcvars`" && cl /nologo /W4 /WX /O2 /MT /Brepro /DARMI_GUI `"$launcher`" /Fo`"$objects\launcher.obj`" /Fe`"$output\ARMI.exe`" /link /Brepro /SUBSYSTEM:WINDOWS shell32.lib user32.lib`""
if ($LASTEXITCODE -ne 0) { throw 'MSIX-LAUNCHER-COMPILE' }
