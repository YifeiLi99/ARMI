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
UninstallFilesDir={app}\control\uninstall
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#PayloadRoot}\*"; DestDir: "{app}\tmp\update\{#PackageId}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadRoot}\bundle.json"; DestDir: "{app}\tmp"; DestName: "activate-{#PackageId}.json"; Flags: ignoreversion; AfterInstall: ActivateProgram

[Icons]
Name: "{group}\ARMI"; Filename: "{app}\ARMI.exe"; Check: ActivationReady
Name: "{group}\卸载 ARMI"; Filename: "{uninstallexe}"; Check: ActivationReady
Name: "{app}\卸载 ARMI"; Filename: "{uninstallexe}"; Check: ActivationReady

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
  LegacyUninstaller: Boolean;
  LegacyExeHash, LegacyDatHash: String;

function IsARMIUninstallLog(const Filename: String): Boolean;
var
  Data: AnsiString;
begin
  { Header of the pinned Inno uninstall-log format: 64-byte ID, 128-byte AppId. }
  Result := LoadStringFromFile(Filename, Data);
  if Result then
    Result := (Copy(Data, 1, 35) = 'Inno Setup Uninstall Log (b) 64-bit') and
      (Copy(Data, 65, 38) = '{C14A7A77-2E62-4F66-AB8A-76459B310416}');
end;

function PreserveUninstallFile(const Source, Dest: String): Boolean;
begin
  Result := FileExists(Dest);
  if Result then Exit;
  Result := FileCopy(Source, Dest + '.pending', False);
  if Result then Result := GetSHA256OfFile(Source) = GetSHA256OfFile(Dest + '.pending');
  if Result then Result := RenameFile(Dest + '.pending', Dest);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldBase, NewBase: String;
begin
  Result := '';
  OldBase := ExpandConstant('{app}\unins000');
  NewBase := ExpandConstant('{app}\control\uninstall\unins000');
  LegacyUninstaller := FileExists(OldBase + '.exe') or FileExists(OldBase + '.dat');
  if not LegacyUninstaller then Exit;
  if not IsARMIUninstallLog(OldBase + '.dat') or
    (not FileExists(OldBase + '.exe') and
      (not FileExists(NewBase + '.exe') or not IsARMIUninstallLog(NewBase + '.dat'))) then begin
    Result := 'ARMI cannot identify the existing uninstall files. No files were removed.';
    Exit;
  end;
  LegacyExeHash := '';
  if FileExists(OldBase + '.exe') then LegacyExeHash := GetSHA256OfFile(OldBase + '.exe');
  LegacyDatHash := GetSHA256OfFile(OldBase + '.dat');
  if not ForceDirectories(ExtractFileDir(NewBase)) then begin
    Result := 'ARMI cannot create its internal uninstall directory.';
    Exit;
  end;
  if FileExists(NewBase + '.dat') then begin
    if not IsARMIUninstallLog(NewBase + '.dat') then
      Result := 'ARMI cannot identify the internal uninstall log.';
  end else if not PreserveUninstallFile(OldBase + '.dat', NewBase + '.dat') then
    Result := 'ARMI could not preserve the existing uninstall log.';
  if Result <> '' then Exit;
  if not PreserveUninstallFile(OldBase + '.exe', NewBase + '.exe') then
    Result := 'ARMI could not preserve the existing uninstaller.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OldBase: String;
begin
  if (CurStep <> ssPostInstall) or not Activated then Exit;
  if LegacyUninstaller then begin
    OldBase := ExpandConstant('{app}\unins000');
    if not FileExists(ExpandConstant('{uninstallexe}')) or
      not IsARMIUninstallLog(ChangeFileExt(ExpandConstant('{uninstallexe}'), '.dat')) or
      (CompareText(ExtractFileDir(ExpandConstant('{uninstallexe}')),
        ExpandConstant('{app}\control\uninstall')) <> 0) or
      ((LegacyExeHash <> '') and (GetSHA256OfFile(OldBase + '.exe') <> LegacyExeHash)) or
      (GetSHA256OfFile(OldBase + '.dat') <> LegacyDatHash) then begin
      Activated := False;
      RaiseException('ARMI could not verify uninstall relocation; old files were retained.');
    end;
    if (FileExists(OldBase + '.exe') and not DeleteFile(OldBase + '.exe')) or
      not DeleteFile(OldBase + '.dat') then begin
      Activated := False;
      RaiseException('ARMI could not remove the old uninstall files.');
    end;
  end;
  DeleteFile(ExpandConstant('{group}\Uninstall ARMI.lnk'));
end;

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
