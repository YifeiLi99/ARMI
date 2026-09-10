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
UninstallDisplayIcon={app}\ARMI.exe
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#PayloadRoot}\*"; DestDir: "{app}\tmp\update\{#PackageId}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadRoot}\bundle.json"; DestDir: "{app}\tmp"; DestName: "activate-{#PackageId}.json"; Flags: ignoreversion; AfterInstall: ActivateProgram

[Icons]
Name: "{group}\ARMI"; Filename: "{app}\ARMI.exe"; Check: ActivationReady
Name: "{group}\Uninstall ARMI"; Filename: "{uninstallexe}"; Check: ActivationReady

[Run]
Filename: "{app}\ARMI.exe"; Description: "Open ARMI"; Flags: postinstall nowait skipifsilent; Check: ActivationReady

[UninstallDelete]
#include UninstallInventory
Type: files; Name: "{app}\ARMI.exe"
Type: files; Name: "{app}\ARMI.exe.pending"
Type: files; Name: "{app}\.current-version"
Type: files; Name: "{app}\.current-version.pending"
Type: files; Name: "{app}\.activation.json"
Type: files; Name: "{app}\.update.lock"

[Code]
var
  Activated: Boolean;

function ActivationReady: Boolean;
begin
  Result := Activated;
end;

function GetCustomSetupExitCode: Integer;
begin
  if Activated then Result := 0 else Result := 9;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not Activated then begin
    WizardForm.FinishedHeadingLabel.Caption := 'ARMI activation failed';
    WizardForm.FinishedLabel.Caption := 'The program switch failed. The previous program and environment data were retained. Close any process using ARMI and run this installer again.';
  end;
end;

procedure ActivateProgram;
var
  ExitCode: Integer;
  ProgramRoot: String;
begin
    ProgramRoot := ExpandConstant('{app}\tmp\update\{#PackageId}');
    Activated := False;
    if not Exec(ProgramRoot + '\runtime\python\pythonw.exe',
      '-I -B -m armi_admin.install_cli activate --installation-root "' + ExpandConstant('{app}') +
      '" --program-root "' + ProgramRoot + '"', '', SW_HIDE,
      ewWaitUntilTerminated, ExitCode) then begin
      Log('ARMI-ACTIVATION-FAILED: activation process could not start');
      Exit;
    end;
    if ExitCode <> 0 then begin
      Log('ARMI-ACTIVATION-FAILED: previous program and environment data retained');
      Exit;
    end;
    Activated := True;
    { The staging interpreter has exited; only this installer-owned staging path is removed. }
    if not DelTree(ProgramRoot, True, True, True) then
      Log('ARMI-STAGING-CLEANUP-PENDING: staging files remain');
    DeleteFile(ExpandConstant('{group}\ARMI Settings.lnk'));
    DeleteFile(ExpandConstant('{app}\tmp\activate-{#PackageId}.json'));
end;

function InitializeUninstall: Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{app}\app\runtime\python\pythonw.exe'),
    '-I -B -m armi_admin.install_cli uninstall --installation-root "' + ExpandConstant('{app}') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
  if not Result then
    MsgBox('ARMI could not verify that its processes have stopped. Uninstall was cancelled; all files and data were retained.', mbError, MB_OK);
end;
