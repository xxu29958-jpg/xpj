#ifndef AppVersion
#define AppVersion "0.0.0-dev"
#endif

#define AppName "Ticketbox"
#define AppPublisher "Ticketbox"

[Setup]
AppId={{C97812CE-7486-41D0-AB68-7558A916F6E3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Ticketbox
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=Ticketbox-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Ticketbox
CloseApplications=no

[Files]
Source: "..\dist\ticketbox-backend\*"; DestDir: "{app}\program\ticketbox-backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\pg\*"; DestDir: "{app}\pg"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\shawl\shawl.exe"; DestDir: "{app}\shawl"; Flags: ignoreversion
Source: "install_bundled_services.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "uninstall_bundled_services.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "DataRoot"; ValueData: "{param:TicketboxDataRoot|{commonappdata}\Ticketbox}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "BackendPort"; ValueData: "{param:TicketboxBackendPort|8000}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "PgPort"; ValueData: "{param:TicketboxPgPort|5432}"; Flags: uninsdeletevalue

[Code]
function Quote(Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function RunPowerShellChecked(ScriptPath: String; Arguments: String; Context: String): Boolean;
var
  ResultCode: Integer;
  Params: String;
begin
  Params := '-NoProfile -ExecutionPolicy Bypass -File ' + Quote(ScriptPath) + ' ' + Arguments;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox(Context + ' could not start PowerShell.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  if ResultCode <> 0 then
  begin
    MsgBox(Context + ' failed. PowerShell exit code: ' + IntToStr(ResultCode), mbError, MB_OK);
    Result := False;
    exit;
  end;

  Result := True;
end;

procedure StopServiceIfPresent(ServiceName: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop ' + ServiceName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopServiceIfPresent('TicketboxBackend');
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Args: String;
begin
  if CurStep = ssPostInstall then
  begin
    Args :=
      '-InstallDir ' + Quote(ExpandConstant('{app}')) +
      ' -DataRoot ' + Quote(ExpandConstant('{param:TicketboxDataRoot|{commonappdata}\Ticketbox}')) +
      ' -PgPort ' + ExpandConstant('{param:TicketboxPgPort|5432}') +
      ' -BackendPort ' + ExpandConstant('{param:TicketboxBackendPort|8000}');
    if not RunPowerShellChecked(
      ExpandConstant('{app}\installer\install_bundled_services.ps1'),
      Args,
      'Ticketbox service installation') then
    begin
      RaiseException('Ticketbox service installation failed.');
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Args: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Args := '-InstallDir ' + Quote(ExpandConstant('{app}'));
    if not RunPowerShellChecked(
      ExpandConstant('{app}\installer\uninstall_bundled_services.ps1'),
      Args,
      'Ticketbox service uninstall') then
    begin
      RaiseException('Ticketbox service uninstall failed.');
    end;
  end;
end;
