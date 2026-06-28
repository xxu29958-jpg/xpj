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
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
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

function ServiceExists(ServiceName: String): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\sc.exe'), 'query ' + ServiceName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := ResultCode = 0;
end;

function IsPortListening(Port: String): Boolean;
var
  ResultCode: Integer;
  Params: String;
begin
  Params := '-NoProfile -ExecutionPolicy Bypass -Command ' +
    Quote('if (Get-NetTCPConnection -State Listen -LocalPort ' + Port + ' -ErrorAction SilentlyContinue) { exit 1 } exit 0');
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := False;
    exit;
  end;
  Result := ResultCode <> 0;
end;

function FreshInstallPortError(): String;
var
  PgPort: String;
  BackendPort: String;
  DataRoot: String;
  BusyPorts: String;
begin
  Result := '';
  DataRoot := ExpandConstant('{param:TicketboxDataRoot|{commonappdata}\Ticketbox}');
  if ServiceExists('TicketboxPg') or DirExists(DataRoot + '\pgdata') then
  begin
    exit;
  end;

  PgPort := ExpandConstant('{param:TicketboxPgPort|5432}');
  BackendPort := ExpandConstant('{param:TicketboxBackendPort|8000}');
  BusyPorts := '';

  if IsPortListening(PgPort) then
  begin
    BusyPorts := 'PostgreSQL port ' + PgPort;
  end;
  if IsPortListening(BackendPort) then
  begin
    if BusyPorts <> '' then
    begin
      BusyPorts := BusyPorts + ', ';
    end;
    BusyPorts := BusyPorts + 'backend port ' + BackendPort;
  end;

  if BusyPorts <> '' then
  begin
    Result :=
      'Ticketbox cannot use the selected ports because they are already in use: ' + BusyPorts + '.' + #13#10 + #13#10 +
      'Close the processes using those ports, or run the installer with another port pair, for example:' + #13#10 +
      'Ticketbox-Setup.exe /TicketboxPgPort=5440 /TicketboxBackendPort=8001';
  end;
end;

procedure StopServiceIfPresent(ServiceName: String);
var
  ResultCode: Integer;
begin
  if ServiceExists(ServiceName) then
  begin
    Exec(ExpandConstant('{sys}\sc.exe'), 'stop ' + ServiceName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(30000);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopServiceIfPresent('TicketboxBackend');
  StopServiceIfPresent('TicketboxPg');
  Result := FreshInstallPortError();
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
