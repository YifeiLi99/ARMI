#ifndef PayloadRoot
  #error PayloadRoot must name a sealed Windows payload
#endif
#ifndef PackageId
  #error PackageId is required
#endif
#ifndef OutputRoot
  #error OutputRoot is required
#endif

[Setup]
AppId={{C14A7A77-2E62-4F66-AB8A-76459B310416}
AppName=ARMI
AppVersion=0.0.0
AppVerName=ARMI 0.0.0 (unsigned local build)
DefaultDirName={localappdata}\Programs\ARMI
DefaultGroupName=ARMI
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir={#OutputRoot}
OutputBaseFilename=ARMI-Windows-x64-{#PackageId}-unsigned
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\armi-desktop.exe
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#PayloadRoot}\*"; DestDir: "{app}\versions\{#PackageId}"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist
Source: "{#PayloadRoot}\*.exe"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\ARMI"; Filename: "{app}\armi-desktop.exe"; Parameters: "--start"
Name: "{group}\ARMI Settings"; Filename: "{app}\armi-desktop.exe"
Name: "{group}\Uninstall ARMI"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\armi-desktop.exe"; Description: "Open ARMI setup (optional features require configuration)"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\.current-version"
Type: files; Name: "{app}\.current-version.pending"
Type: files; Name: "{app}\.activation.json"
Type: files; Name: "{app}\.update.lock"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  ProgramRoot: String;
begin
  if CurStep = ssPostInstall then begin
    ProgramRoot := ExpandConstant('{app}\versions\{#PackageId}');
    if not Exec(ProgramRoot + '\armi-install-control.exe',
      'activate --installation-root "' + ExpandConstant('{app}') +
      '" --program-root "' + ProgramRoot + '"', '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode) then
      RaiseException('ARMI activation could not start. The previous program remains selected.');
    if ExitCode <> 0 then
      RaiseException('ARMI activation failed. The previous program and environment data were retained.');
  end;
end;

function InitializeUninstall: Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{app}\armi-install-control.exe'),
    'uninstall --installation-root "' + ExpandConstant('{app}') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
  if not Result then
    MsgBox('ARMI could not verify that its processes have stopped. Uninstall was cancelled; all files and data were retained.', mbError, MB_OK);
end;
