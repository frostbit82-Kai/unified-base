; Unified Base - Windows installer (Inno Setup 6).
; Built by installer\build_windows.py, which stages the files and passes
; AppVersion, Stage and Art (the wizard images). Keep this file ASCII.
#ifndef Stage
  #error Build with installer\build_windows.py - it stages the files this packs.
#endif

#define AppName "Unified Base"
#define AppId "BomsAI.UnifiedBase"
; pythonw: no console. Qt then starts each module with CREATE_NO_WINDOW, so
; console programs open no window either. -E -s: ignore PYTHONPATH and the
; user's own site-packages, which would load ahead of the bundled Qt.
#define AppExe "{app}\runtime\pythonw.exe"
#define AppArgs '-E -s ""{app}\app\main.py""'
#define PowerShell "{sys}\WindowsPowerShell\v1.0\powershell.exe"
; Single quotes: ISPP keeps the "" that Inno then reads as one quote.
#define WslSetup '-NoProfile -ExecutionPolicy Bypass -File ""{app}\app\setup-wsl.ps1""'

[Setup]
AppId={{E267481C-3340-45D2-AA44-CA0B3E4ABB9D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} (beta)
AppPublisher=BomsAI Software
AppPublisherURL=https://bomsaisoftware.com/software/unified-base
AppSupportURL=https://bomsaisoftware.com/software/unified-base-guide
VersionInfoVersion={#AppVersion}
; Per user, no UAC: {autopf} is %LOCALAPPDATA%\Programs. The folder has to
; be writable - the demos build inside it.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Qt 6 needs Windows 10 1809 or later.
MinVersion=10.0.17763
OutputBaseFilename=UnifiedBase-{#AppVersion}-windows-x64-setup
SetupIconFile={#Stage}\unified-base.ico
WizardSmallImageFile={#Art}\wizard-small.bmp
WizardImageFile={#Art}\wizard-large.bmp,{#Art}\wizard-large-2x.bmp
WizardStyle=modern
UninstallDisplayIcon={app}\unified-base.ico
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
SetupLogging=yes
; NextButtonClick below refuses while it runs; Restart Manager is the
; fallback for anything else holding a file, but nothing is restarted.
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Replace the program wholesale, as the Linux installer does, so an upgrade
; never runs next to a file the new build dropped. The demos' build output
; goes with it; each demo rebuilds on its first Start.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; AppUserModelID matches the one main.py sets, so a taskbar pin of the running
; window pins this shortcut - not pythonw.exe, which would start nothing.
Name: "{group}\{#AppName}"; Filename: "{#AppExe}"; Parameters: "{#AppArgs}"; WorkingDir: "{app}\app"; IconFilename: "{app}\unified-base.ico"; AppUserModelID: "{#AppId}"; Comment: "Run programs in any language side by side"
Name: "{group}\Set Up Linux Programs (WSL)"; Filename: "{#PowerShell}"; Parameters: "{#WslSetup}"; WorkingDir: "{app}"; Comment: "Optional: run Linux programs inside Unified Base through WSL"
Name: "{group}\{#AppName} Self-Test"; Filename: "{app}\selftest.bat"; WorkingDir: "{app}"; IconFilename: "{app}\unified-base.ico"; Comment: "Check what works on this PC"
Name: "{group}\Read Me"; Filename: "{app}\README.txt"
Name: "{autodesktop}\{#AppName}"; Filename: "{#AppExe}"; Parameters: "{#AppArgs}"; WorkingDir: "{app}\app"; IconFilename: "{app}\unified-base.ico"; AppUserModelID: "{#AppId}"; Tasks: desktopicon

[Run]
Filename: "{#AppExe}"; Parameters: "{#AppArgs}"; WorkingDir: "{app}\app"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{#PowerShell}"; Parameters: "{#WslSetup}"; WorkingDir: "{app}"; Description: "Set up Linux programs (WSL) - optional, see the Read Me"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\README.txt"; Description: "Open the Read Me"; Flags: nowait postinstall skipifsilent shellexec unchecked

[UninstallDelete]
; The demos' build output and the byte-code made since install. The user's
; modules, settings and environments are in %USERPROFILE%\.unified_base and stay.
Type: filesandordirs; Name: "{app}"

[Code]
{ The first process found running from Dir (the app, a module it built, or a
  Python module's interpreter, which is the bundled one), or ''. WMI filters:
  walking every process from here took 10 s. }
function RunningFrom(const Dir: String): String;
var
  Locator, Service, Procs: Variant;
  Prefix: String;
begin
  Result := '';
  { WQL string: backslash and quote are escaped with a backslash. A LIKE
    wildcard (_) in the path only widens the match. }
  Prefix := AddBackslash(Dir);
  StringChangeEx(Prefix, '\', '\\', True);
  StringChangeEx(Prefix, '''', '\''', True);
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    { Not unins000.exe: the uninstaller's first stage runs from Dir and
      waits for the second, which is the one asking. }
    Procs := Service.ExecQuery('SELECT Name FROM Win32_Process WHERE ' +
      'ExecutablePath LIKE ''' + Prefix + '%'' AND NOT Name LIKE ''unins%''');
    if Procs.Count > 0 then
      Result := Procs.ItemIndex(0).Name;
  except
    { No WMI: Restart Manager still catches files in use. }
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Running: String;
begin
  Result := True;
  if CurPageID = wpReady then begin
    Running := RunningFrom(ExpandConstant('{app}'));
    if Running <> '' then begin
      SuppressibleMsgBox('Unified Base is running (' + Running + '). Quit it with ' +
        'File > Exit, then click Install again.', mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

{ Not a formality: this imports the app and opens Qt, so a PC missing
  something says so now, not on a double-click that seems to do nothing.
  It also leaves main.py's byte-code, so the first start is quicker. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code, I: Integer;
  Output: TExecOutput;
  Detail: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  WizardForm.StatusLabel.Caption := 'Checking that Unified Base starts...';
  if ExecAndCaptureOutput(ExpandConstant('{app}\runtime\python.exe'),
       '-E -s -c "import sys; sys.path.insert(0, sys.argv[1]); import main; ' +
       'from PySide6.QtWidgets import QApplication; QApplication([])" "' +
       ExpandConstant('{app}\app') + '"', ExpandConstant('{app}'), SW_HIDE,
       ewWaitUntilTerminated, Code, Output) and (Code = 0) then
    Exit;
  Detail := '';
  for I := 0 to GetArrayLength(Output.StdErr) - 1 do
    Detail := Detail + Output.StdErr[I] + #13#10;
  Log('Start check failed (' + IntToStr(Code) + '):'#13#10 + Detail);
  SuppressibleMsgBox('Unified Base is installed, but it did not start here:' + #13#10#13#10 +
    Copy(Detail, Length(Detail) - 1500, 1500) + #13#10 +
    'Run "Unified Base Self-Test" from the Start menu for details, and see ' +
    '"If it will not start" in the Read Me.', mbError, MB_OK, IDOK);
end;

function InitializeUninstall(): Boolean;
var
  Running: String;
begin
  Running := RunningFrom(ExpandConstant('{app}'));
  Result := Running = '';
  if not Result then
    SuppressibleMsgBox('Unified Base is running (' + Running + '). Quit it with ' +
      'File > Exit, then uninstall again.', mbError, MB_OK, IDOK);
end;

{ Everything Unified Base made outside its folder: the user data folder (with
  the toolchains modules fetched into it), the Linux modules' environments
  in WSL's home, and Edge profiles a crash left in %TEMP% (web modules;
  normally removed on Stop). The fetched Ruby is an install of its own, so
  its uninstaller runs first, or Installed Apps keeps a dead entry. Rust
  (rustup, in ~\.cargo as rustup puts it), WSL, VcXsrv and Docker are
  programs of their own and stay. }
procedure DeleteData(const Data: String);
var
  Distro: String;
  Code: Integer;
begin
  { .NET's compiler server outlives a build by 10 minutes, holding files. }
  if FileExists(Data + '\toolchains\dotnet\dotnet.exe') then
    Exec(Data + '\toolchains\dotnet\dotnet.exe', 'build-server shutdown', '',
      SW_HIDE, ewWaitUntilTerminated, Code);
  if FileExists(Data + '\toolchains\ruby\unins000.exe') then
    Exec(Data + '\toolchains\ruby\unins000.exe', '/VERYSILENT /SUPPRESSMSGBOXES',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
  DelTree(Data, True, True, True);
  DelTree(GetTempDir + 'ub_web_*', False, True, True);
  if FileExists(ExpandConstant('{sys}\wsl.exe')) and RegQueryStringValue(HKCU,
       'Software\Microsoft\Windows\CurrentVersion\Lxss', 'DefaultDistribution',
       Distro) then
    Exec(ExpandConstant('{sys}\wsl.exe'), '--exec sh -c "cd && rm -rf .unified_base"',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ Asked, No by default: the data includes the projects made with New Blank
  Tab, which are the user's own work. /DELETEDATA=yes answers yes for a
  silent uninstall. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  Data := ExpandConstant('{%USERPROFILE}\.unified_base');
  if (CurUninstallStep <> usPostUninstall) or not DirExists(Data) then
    Exit;
  if (Lowercase(ExpandConstant('{param:DELETEDATA|no}')) = 'yes') or
     (not UninstallSilent and (MsgBox('Unified Base is removed.' + #13#10#13#10 +
       'Also delete your Unified Base data? That is your module list, layouts ' +
       'and settings, the languages it downloaded, every module''s ' +
       'environment and log, and the projects you made with New Blank Tab:' + #13#10#13#10 + Data + #13#10#13#10 +
       'Project folders you added from elsewhere are not touched. Keep the ' +
       'data to pick up where you left off after reinstalling.',
       mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES)) then begin
    DeleteData(Data);
    if DirExists(Data) then
      SuppressibleMsgBox('Some of ' + Data + ' could not be deleted (a file in ' +
        'use?). Delete what is left yourself.', mbError, MB_OK, IDOK);
  end;
end;
