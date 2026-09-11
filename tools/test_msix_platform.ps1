[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [string]$PackageDirectory,
    [string]$CertificateThumbprint
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$packageName = 'YifeiLi99.ARMI.MsixAcceptance'
$publisher = 'CN=ARMI MSIX Acceptance'
$sdk = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64'
$output = if ($PackageDirectory) { [IO.Path]::GetFullPath($PackageDirectory) } else { Join-Path $workspace ('.tmp/msix-platform-' + [Guid]::NewGuid().ToString('N')) }
$payload = Join-Path $output 'payload'
if (Get-AppxPackage -Name $packageName) { throw 'MSIX-TEST-PACKAGE-ALREADY-INSTALLED' }
if (-not $PackageDirectory) {
New-Item -ItemType Directory -Path $payload -Force | Out-Null
$vcvars = Join-Path $workspace '.armi-tools/installs/msvc/VC/Auxiliary/Build/vcvars64.bat'
$source = Join-Path $PSScriptRoot 'windows/msix_probe.cpp'
& $env:ComSpec /d /s /c "`"call `"$vcvars`" && cl /nologo /std:c++20 /EHsc /W4 /WX /O2 /MT `"$source`" /Fo`"$output\probe.obj`" /Fe`"$payload\ARMI.exe`" /link windowsapp.lib shell32.lib ole32.lib`""
if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-COMPILE' }
& (Join-Path $PSScriptRoot 'build_windows_platform.ps1') -OutputDirectory $payload -LibraryOnly
$database = [ordered]@{postgresql='18.4'; vector='0.8.6'; pg_trgm='1.6'; baseline='0000'; schema_digest='probe-schema'; role_policy_digest='probe-roles'}
# Generated geometric assets are used only by this isolated platform probe.
Add-Type -AssemblyName System.Drawing
foreach ($size in @(50, 44, 150)) {
    $bitmap = [Drawing.Bitmap]::new($size, $size)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::FromArgb(32, 72, 96))
    $bitmap.Save((Join-Path $payload "logo$size.png"), [Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
}
$certificate = if ($CertificateThumbprint) {
    if ($CertificateThumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'MSIX-PROBE-CERTIFICATE' }
    Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $CertificateThumbprint)
} else {
    New-SelfSignedCertificate -Type Custom -Subject $publisher -KeyUsage DigitalSignature -FriendlyName 'ARMI isolated MSIX acceptance' -CertStoreLocation Cert:\CurrentUser\My -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}') -NotAfter (Get-Date).AddDays(7)
}
if ($certificate.Subject -ne $publisher -or -not $certificate.HasPrivateKey) { throw 'MSIX-PROBE-CERTIFICATE' }
$publicCertificate = Join-Path $output 'acceptance.cer'
Export-Certificate -Cert $certificate -FilePath $publicCertificate | Out-Null
try {
    foreach ($version in @('0.0.1.0', '0.0.2.0', '0.0.3.0')) {
        $database.schema_digest = if ($version -eq '0.0.3.0') { 'incompatible-schema' } else { 'probe-schema' }
        [IO.File]::WriteAllText((Join-Path $payload 'bundle.json'), (@{database=$database} | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        $xml = @"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10" xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10" xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10" xmlns:uap5="http://schemas.microsoft.com/appx/manifest/uap/windows10/5" xmlns:desktop4="http://schemas.microsoft.com/appx/manifest/desktop/windows10/4" xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities" xmlns:virtualization="http://schemas.microsoft.com/appx/manifest/virtualization/windows10" IgnorableNamespaces="uap desktop uap5 desktop4 rescap virtualization">
  <Identity Name="$packageName" Publisher="$publisher" Version="$version" ProcessorArchitecture="x64"/>
  <Properties><DisplayName>ARMI MSIX Acceptance</DisplayName><PublisherDisplayName>ARMI Acceptance</PublisherDisplayName><Logo>logo50.png</Logo><virtualization:FileSystemWriteVirtualization><virtualization:ExcludedDirectories><virtualization:ExcludedDirectory>`$(KnownFolder:LocalAppData)\ARMI.MsixAcceptance</virtualization:ExcludedDirectory></virtualization:ExcludedDirectories></virtualization:FileSystemWriteVirtualization></Properties>
  <Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.22000.0" MaxVersionTested="10.0.26100.0"/></Dependencies>
  <Resources><Resource Language="zh-CN"/></Resources>
  <Applications><Application Id="ARMI" Executable="ARMI.exe" EntryPoint="Windows.FullTrustApplication" desktop4:SupportsMultipleInstances="true"><uap:VisualElements DisplayName="ARMI MSIX Acceptance" Description="Isolated platform acceptance" BackgroundColor="transparent" Square150x150Logo="logo150.png" Square44x44Logo="logo44.png"/><Extensions><uap5:Extension Category="windows.appExecutionAlias" Executable="ARMI.exe" EntryPoint="Windows.FullTrustApplication"><uap5:AppExecutionAlias desktop4:Subsystem="console"><uap5:ExecutionAlias Alias="ARMI.MsixAcceptance.exe"/></uap5:AppExecutionAlias></uap5:Extension><desktop:Extension Category="windows.startupTask" Executable="ARMI.exe" EntryPoint="Windows.FullTrustApplication"><desktop:StartupTask TaskId="ARMIStartup" Enabled="false" DisplayName="ARMI MSIX Acceptance"/></desktop:Extension></Extensions></Application></Applications>
  <Capabilities><rescap:Capability Name="runFullTrust"/><rescap:Capability Name="unvirtualizedResources"/></Capabilities>
</Package>
"@
        [IO.File]::WriteAllText((Join-Path $payload 'AppxManifest.xml'), $xml, [Text.UTF8Encoding]::new($false))
        $package = Join-Path $output "ARMI-$version.msix"
        & "$sdk\makeappx.exe" pack /d $payload /p $package /o
        if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-PACK' }
        & "$sdk\signtool.exe" sign /fd SHA256 /sha1 $certificate.Thumbprint $package
        if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-SIGN' }
    }
    # Negative packages exercise Windows signature verification, not mocks.
    $xml = $xml.Replace('Version="0.0.3.0"', 'Version="0.0.4.0"').Replace('Name="' + $packageName + '"', 'Name="YifeiLi99.ARMI.WrongAcceptance"')
    [IO.File]::WriteAllText((Join-Path $payload 'AppxManifest.xml'), $xml, [Text.UTF8Encoding]::new($false))
    & "$sdk\makeappx.exe" pack /d $payload /p (Join-Path $output 'wrong-identity.msix') /o
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-WRONG-IDENTITY-PACK' }
    & "$sdk\signtool.exe" sign /fd SHA256 /sha1 $certificate.Thumbprint (Join-Path $output 'wrong-identity.msix')
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-WRONG-IDENTITY-SIGN' }
    $untrusted = New-SelfSignedCertificate -Type Custom -Subject 'CN=ARMI Untrusted Acceptance' -KeyUsage DigitalSignature -CertStoreLocation Cert:\CurrentUser\My -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}') -NotAfter (Get-Date).AddDays(1)
    try {
        $xml = $xml.Replace('Name="YifeiLi99.ARMI.WrongAcceptance"', 'Name="' + $packageName + '"').Replace($publisher, $untrusted.Subject)
        [IO.File]::WriteAllText((Join-Path $payload 'AppxManifest.xml'), $xml, [Text.UTF8Encoding]::new($false))
        & "$sdk\makeappx.exe" pack /d $payload /p (Join-Path $output 'untrusted.msix') /o
        if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-UNTRUSTED-PACK' }
        & "$sdk\signtool.exe" sign /fd SHA256 /sha1 $untrusted.Thumbprint (Join-Path $output 'untrusted.msix')
        if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-UNTRUSTED-SIGN' }
    } finally {
        Remove-Item -LiteralPath ("Cert:\CurrentUser\My\" + $untrusted.Thumbprint) -DeleteKey
    }
    $corrupt = [IO.File]::ReadAllBytes((Join-Path $output 'ARMI-0.0.2.0.msix'))
    $corrupt[0] = $corrupt[0] -bxor 255
    [IO.File]::WriteAllBytes((Join-Path $output 'corrupt.msix'), $corrupt)
} finally {
    if (-not $CertificateThumbprint) {
        Write-Output ("Acceptance signer retained in CurrentUser certificate store: " + $certificate.Thumbprint)
    }
}
}
if ($PrepareOnly) {
    Write-Output "Signed acceptance packages prepared (local trust and installation not verified): $output"
    return
}
# Trust must be provisioned separately by an administrator. Never weaken deployment policy.
foreach ($version in @('0.0.1.0', '0.0.2.0')) {
    & "$sdk\signtool.exe" verify /pa (Join-Path $output "ARMI-$version.msix")
    if ($LASTEXITCODE -ne 0) { throw "MSIX-PROBE-TRUST-REQUIRED: $output\acceptance.cer" }
}
try {
    Add-AppxPackage -Path (Join-Path $output 'ARMI-0.0.1.0.msix')
    $family = (Get-AppxPackage -Name $packageName).PackageFamilyName
    $alias = Join-Path $env:LOCALAPPDATA 'Microsoft/WindowsApps/ARMI.MsixAcceptance.exe'
    & $alias
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-ALIAS' }
    & $alias repeat-native
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-REPEATED-ABI' }
    & $alias native 1 (Join-Path $output 'ARMI-0.0.2.0.msix')
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-TRUSTED-CANDIDATE' }
    & $alias native 1 (Join-Path $output 'ARMI-0.0.3.0.msix')
    if ($LASTEXITCODE -eq 0) { throw 'MSIX-PROBE-INCOMPATIBLE-ACCEPTED' }
    & $alias native 1 (Join-Path $output 'ARMI-0.0.1.0.msix')
    if ($LASTEXITCODE -eq 0) { throw 'MSIX-PROBE-NONINCREASING-ACCEPTED' }
    foreach ($rejected in @('wrong-identity.msix', 'untrusted.msix', 'corrupt.msix')) {
        & $alias native 1 (Join-Path $output $rejected)
        if ($LASTEXITCODE -eq 0) { throw "MSIX-PROBE-INVALID-CANDIDATE-ACCEPTED: $rejected" }
    }
    $environmentId = [Guid]::NewGuid().ToString()
    & $alias host-child $environmentId
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-HOST-CHILD' }
    & $alias host-child $environmentId
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-SECOND-CALLER' }
    $executable = (Get-AppxPackage -Name $packageName).InstallLocation + '\ARMI.exe'
    $owned = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $executable })
    $hostProcess = @($owned | Where-Object { $_.CommandLine -like "*--environment-host $environmentId*" })
    if ($hostProcess.Count -ne 1 -or $owned.Count -lt 5) { throw 'MSIX-PROBE-CLI-EXIT-LIFETIME' }
    Stop-Process -Id $hostProcess[0].ProcessId
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $executable })
        if (-not $remaining.Count) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($remaining.Count) { throw 'MSIX-PROBE-HOST-ORPHANS' }
    $marker = Join-Path $env:LOCALAPPDATA 'ARMI.MsixAcceptance/probe.txt'
    if ((Get-Content -LiteralPath $marker -Raw) -ne '0.0.1.0') { throw 'MSIX-PROBE-DATA-LOCATION' }
    & $alias defer ([Uri](Join-Path $output 'ARMI-0.0.2.0.msix')).AbsoluteUri
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-DEFER' }
    # A real application activation completes deferred registration. Merely
    # polling the installed version does not activate a staged package.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IArmiProbeActivation {
    [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string app, [MarshalAs(UnmanagedType.LPWStr)] string args, uint options, out uint pid);
}
public static class ArmiProbeActivation {
    public static uint Start(string app) {
        var obj = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
        try {
            uint pid;
            Marshal.ThrowExceptionForHR(((IArmiProbeActivation)obj).ActivateApplication(app, "", 0, out pid));
            return pid;
        } finally { Marshal.ReleaseComObject(obj); }
    }
}
'@
    $activatedPid = [ArmiProbeActivation]::Start($family + '!ARMI')
    $activatedProcess = Get-Process -Id $activatedPid -ErrorAction SilentlyContinue
    if ($activatedProcess -and -not $activatedProcess.WaitForExit(30000)) { throw 'MSIX-PROBE-ACTIVATION-TIMEOUT' }
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $installed = Get-AppxPackage -Name $packageName
        if ($installed -and $installed.Version -eq '0.0.2.0' -and (Test-Path -LiteralPath $alias)) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $installed -or $installed.Version -ne '0.0.2.0') { throw 'MSIX-PROBE-REGISTRATION-TIMEOUT' }
    & $alias
    if ($LASTEXITCODE -ne 0 -or (Get-Content -LiteralPath $marker -Raw) -ne '0.0.2.0') { throw 'MSIX-PROBE-NEXT-ACTIVATION' }
    & $alias host-child $environmentId
    if ($LASTEXITCODE -ne 0) { throw 'MSIX-PROBE-UNINSTALL-CHILD' }
    $executable = (Get-AppxPackage -Name $packageName).InstallLocation + '\ARMI.exe'
    Get-AppxPackage -Name $packageName | Remove-AppxPackage
    if (Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $executable }) { throw 'MSIX-PROBE-UNINSTALL-ORPHANS' }
    if (-not (Test-Path -LiteralPath $marker)) { throw 'MSIX-PROBE-UNINSTALL-RETENTION' }
    Write-Output "MSIX platform probe passed: $output"
} finally {
    Get-AppxPackage -Name $packageName | Remove-AppxPackage
}
