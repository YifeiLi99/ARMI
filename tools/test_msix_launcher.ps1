[CmdletBinding()]
param([Parameter(Mandatory)][string]$CertificateThumbprint)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = Join-Path $workspace ('.tmp/msix-launcher-' + [Guid]::NewGuid().ToString('N'))
$payload = Join-Path $output 'payload'
$packageName = 'YifeiLi99.ARMI.MsixAcceptance'
$sdk = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64'
if (Get-AppxPackage -Name $packageName) { throw 'MSIX-TEST-PACKAGE-ALREADY-INSTALLED' }
if ($CertificateThumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'MSIX-PROBE-CERTIFICATE' }
$certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $CertificateThumbprint)
if ($certificate.Subject -ne 'CN=ARMI MSIX Acceptance' -or -not $certificate.HasPrivateKey) { throw 'MSIX-PROBE-CERTIFICATE' }
New-Item -ItemType Directory -Path $payload -Force | Out-Null
$vcvars = Join-Path $workspace '.armi-tools/installs/msvc/VC/Auxiliary/Build/vcvars64.bat'
$source = Join-Path $PSScriptRoot 'windows/launcher.c'
& $env:ComSpec /d /s /c "`"call `"$vcvars`" && cl /nologo /W4 /WX /O2 /MT /DARMI_GUI `"$source`" /Fo`"$output\launcher.obj`" /Fe`"$payload\ARMI.exe`" /link /SUBSYSTEM:WINDOWS shell32.lib user32.lib ole32.lib uuid.lib`""
if ($LASTEXITCODE -ne 0) { throw 'MSIX-LAUNCHER-COMPILE' }
# The real launcher is packaged without Python or the ARMI DLL on purpose.
Add-Type -AssemblyName System.Drawing
foreach ($size in @(50, 44, 150)) {
    $bitmap = [Drawing.Bitmap]::new($size, $size)
    $bitmap.Save((Join-Path $payload "logo$size.png"), [Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
}
$manifest = @'
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10" xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10" xmlns:uap5="http://schemas.microsoft.com/appx/manifest/uap/windows10/5" xmlns:desktop4="http://schemas.microsoft.com/appx/manifest/desktop/windows10/4" xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities" xmlns:virtualization="http://schemas.microsoft.com/appx/manifest/virtualization/windows10" IgnorableNamespaces="uap uap5 desktop4 rescap virtualization">
  <Identity Name="YifeiLi99.ARMI.MsixAcceptance" Publisher="CN=ARMI MSIX Acceptance" Version="0.0.4.0" ProcessorArchitecture="x64"/>
  <Properties><DisplayName>ARMI launcher acceptance</DisplayName><PublisherDisplayName>ARMI Acceptance</PublisherDisplayName><Logo>logo50.png</Logo><virtualization:FileSystemWriteVirtualization><virtualization:ExcludedDirectories><virtualization:ExcludedDirectory>$(KnownFolder:LocalAppData)\ARMI.MsixAcceptance</virtualization:ExcludedDirectory></virtualization:ExcludedDirectories></virtualization:FileSystemWriteVirtualization></Properties>
  <Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.22000.0" MaxVersionTested="10.0.26100.0"/></Dependencies>
  <Resources><Resource Language="zh-CN"/></Resources>
  <Applications><Application Id="ARMI" Executable="ARMI.exe" EntryPoint="Windows.FullTrustApplication" desktop4:SupportsMultipleInstances="true"><uap:VisualElements DisplayName="ARMI launcher acceptance" Description="Isolated early failure verification" BackgroundColor="transparent" Square150x150Logo="logo150.png" Square44x44Logo="logo44.png"/><Extensions><uap5:Extension Category="windows.appExecutionAlias" Executable="ARMI.exe" EntryPoint="Windows.FullTrustApplication"><uap5:AppExecutionAlias desktop4:Subsystem="console"><uap5:ExecutionAlias Alias="ARMI.MsixAcceptance.exe"/></uap5:AppExecutionAlias></uap5:Extension></Extensions></Application></Applications>
  <Capabilities><rescap:Capability Name="runFullTrust"/><rescap:Capability Name="unvirtualizedResources"/></Capabilities>
</Package>
'@
[IO.File]::WriteAllText((Join-Path $payload 'AppxManifest.xml'), $manifest, [Text.UTF8Encoding]::new($false))
$package = Join-Path $output 'launcher.msix'
& "$sdk\makeappx.exe" pack /d $payload /p $package /o
if ($LASTEXITCODE -ne 0) { throw 'MSIX-LAUNCHER-PACK' }
& "$sdk\signtool.exe" sign /fd SHA256 /sha1 $certificate.Thumbprint $package
if ($LASTEXITCODE -ne 0) { throw 'MSIX-LAUNCHER-SIGN' }
& "$sdk\signtool.exe" verify /pa $package
if ($LASTEXITCODE -ne 0) { throw 'MSIX-LAUNCHER-TRUST' }
$probeRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'ARMI.MsixAcceptance'))
if (Test-Path -LiteralPath $probeRoot) { throw 'MSIX-LAUNCHER-EXISTING-DATA' }
$logs = Join-Path $probeRoot 'control/logs'
$saved = Join-Path $output 'diagnostics'
New-Item -ItemType Directory -Path $saved | Out-Null
function Save-LauncherLogs([string]$directory, [string]$expectedPhase, [string]$expectedMode) {
    $records = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $directory -File)) {
        if ($file.Name -notmatch '^launcher-[0-9a-fA-F-]+\.(jsonl|lease|summary\.json)$') { throw 'MSIX-LAUNCHER-UNEXPECTED-FILE' }
        if ($file.Extension -eq '.jsonl') {
            $raw = Get-Content -LiteralPath $file.FullName -Raw
            if ($raw.Contains('private-marker')) { throw 'MSIX-LAUNCHER-ARGUMENT-LEAK' }
            $records += @($raw.Trim().Split("`n") | ForEach-Object { $_ | ConvertFrom-Json })
        }
        Copy-Item -LiteralPath $file.FullName -Destination $saved
        Remove-Item -LiteralPath $file.FullName
    }
    $failure = @($records | Where-Object event -eq 'process.launcher.failed')
    if ($failure.Count -ne 1 -or $failure[0].details.phase -ne $expectedPhase -or
        $failure[0].details.winerror -eq 0 -or [string]::IsNullOrWhiteSpace($failure[0].details.system_message) -or $failure[0].details.exit_code -ne 2 -or
        $failure[0].sink_mode -ne $expectedMode -or $failure[0].version -ne '0.0.4.0') { throw 'MSIX-LAUNCHER-FAILURE-EVIDENCE' }
}
try {
    Add-AppxPackage -Path $package
    $alias = Join-Path $env:LOCALAPPDATA 'Microsoft/WindowsApps/ARMI.MsixAcceptance.exe'
    foreach ($case in @('python', 'dll', 'emergency', 'unavailable')) {
        $arguments = if ($case -eq 'dll') { @('--environment-host', [Guid]::NewGuid().ToString()) } else { @('cli', 'admin', 'private-marker') }
        if ($case -eq 'emergency') {
            [IO.Directory]::Delete($logs)
            [IO.File]::WriteAllText($logs, 'isolated directory failure')
        }
        if ($case -eq 'unavailable') {
            $emergencyLogs = Join-Path $probeRoot 'control/emergency/logs'
            [IO.Directory]::Delete($emergencyLogs)
            [IO.File]::WriteAllText($emergencyLogs, 'isolated emergency directory failure')
        }
        $process = Start-Process -FilePath $alias -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $output "$case.stdout") -RedirectStandardError (Join-Path $output "$case.stderr")
        if ($process.ExitCode -ne 2) { throw 'MSIX-LAUNCHER-EXIT' }
        if ((Get-Item -LiteralPath (Join-Path $output "$case.stdout")).Length -ne 0) { throw 'MSIX-LAUNCHER-PROTOCOL-STDOUT' }
        if ($case -eq 'unavailable') {
            $stderr = Get-Content -LiteralPath (Join-Path $output "$case.stderr") -Raw
            if (-not $stderr.Contains('ARMI-LAUNCHER-DIAGNOSTIC-PERSISTENCE-UNAVAILABLE')) { throw 'MSIX-LAUNCHER-SILENT-LOG-LOSS' }
            [IO.File]::Delete($emergencyLogs)
            [IO.Directory]::CreateDirectory($emergencyLogs) | Out-Null
            continue
        }
        $directory = if ($case -eq 'emergency') { Join-Path $probeRoot 'control/emergency/logs' } else { $logs }
        Save-LauncherLogs $directory $(if ($case -eq 'dll') { 'load_platform_library' } else { 'start_python' }) $(if ($case -eq 'emergency') { 'emergency' } else { 'file' })
    }
} finally {
    Get-AppxPackage -Name $packageName | Remove-AppxPackage
}
# Only this invocation's known fixture files and empty directories are removed.
[IO.File]::Delete($logs)
[IO.Directory]::Delete((Join-Path $probeRoot 'control/emergency/logs'))
[IO.Directory]::Delete((Join-Path $probeRoot 'control/emergency'))
[IO.Directory]::Delete((Join-Path $probeRoot 'control'))
[IO.Directory]::Delete($probeRoot)
Write-Output "MSIX launcher failure acceptance passed: $output"
