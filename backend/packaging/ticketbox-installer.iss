#ifndef AppVersion
#define AppVersion "0.0.0-dev"
#endif
#ifndef AppVersionInfo
#define AppVersionInfo "0.0.0.0"
#endif

#define AppName "小票夹后端服务"
#define AppPublisher "小票夹"

[Setup]
AppId={{C97812CE-7486-41D0-AB68-7558A916F6E3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Ticketbox
DefaultGroupName=小票夹
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=Ticketbox-Setup-{#AppVersion}
SetupIconFile=ticketbox.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\ticketbox.ico
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=小票夹后端服务安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersionInfo}
CloseApplications=no

[Files]
Source: "ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ticketbox-backend\*"; DestDir: "{app}\program\ticketbox-backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\pg\*"; DestDir: "{app}\pg"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\shawl\shawl.exe"; DestDir: "{app}\shawl"; Flags: ignoreversion
Source: "install_bundled_services.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "uninstall_bundled_services.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "DataRoot"; ValueData: "{code:GetDataRoot}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "BackendPort"; ValueData: "{code:GetBackendPort}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "PgPort"; ValueData: "{code:GetPgPort}"; Flags: uninsdeletevalue

[Icons]
Name: "{autoprograms}\小票夹\打开小票夹 Web"; Filename: "http://127.0.0.1:{code:GetBackendPort}/web"; IconFilename: "{app}\ticketbox.ico"
Name: "{autoprograms}\小票夹\数据目录"; Filename: "{code:GetDataRoot}"; IconFilename: "{app}\ticketbox.ico"

[Code]
var
  DataRootPage: TInputDirWizardPage;
  PortPage: TInputQueryWizardPage;
  ExistingInstall: Boolean;
  ExistingDataRoot: String;
  ExistingPgPort: String;
  ExistingBackendPort: String;

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

procedure LoadExistingConfig();
begin
  ExistingDataRoot := '';
  ExistingPgPort := '';
  ExistingBackendPort := '';

  RegQueryStringValue(HKLM, 'Software\Ticketbox', 'DataRoot', ExistingDataRoot);
  RegQueryStringValue(HKLM, 'Software\Ticketbox', 'PgPort', ExistingPgPort);
  RegQueryStringValue(HKLM, 'Software\Ticketbox', 'BackendPort', ExistingBackendPort);

  ExistingInstall :=
    (ExistingDataRoot <> '') or
    ServiceExists('TicketboxPg') or
    ServiceExists('TicketboxBackend');
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

function IsValidPort(Port: String): Boolean;
var
  PortNumber: Integer;
begin
  PortNumber := StrToIntDef(Trim(Port), -1);
  Result := (PortNumber >= 1) and (PortNumber <= 65535);
end;

function SelectInitialDataRoot(): String;
var
  ParamValue: String;
begin
  ParamValue := ExpandConstant('{param:TicketboxDataRoot|}');
  if ParamValue <> '' then
  begin
    Result := ParamValue;
  end
  else if ExistingDataRoot <> '' then
  begin
    Result := ExistingDataRoot;
  end
  else
  begin
    Result := ExpandConstant('{commonappdata}\Ticketbox');
  end;
end;

function SelectInitialPort(ParamName: String; ExistingValue: String; DefaultValue: String; FallbackValue: String): String;
var
  ParamValue: String;
begin
  ParamValue := ExpandConstant('{param:' + ParamName + '|}');
  if ParamValue <> '' then
  begin
    Result := ParamValue;
  end
  else if ExistingValue <> '' then
  begin
    Result := ExistingValue;
  end
  else if (not ExistingInstall) and IsPortListening(DefaultValue) and (not IsPortListening(FallbackValue)) then
  begin
    Result := FallbackValue;
  end
  else
  begin
    Result := DefaultValue;
  end;
end;

function SelectedDataRoot(): String;
begin
  if DataRootPage <> nil then
  begin
    Result := Trim(DataRootPage.Values[0]);
  end
  else
  begin
    Result := SelectInitialDataRoot();
  end;
end;

function SelectedPgPort(): String;
begin
  if PortPage <> nil then
  begin
    Result := Trim(PortPage.Values[0]);
  end
  else
  begin
    Result := SelectInitialPort('TicketboxPgPort', ExistingPgPort, '5432', '5440');
  end;
end;

function SelectedBackendPort(): String;
begin
  if PortPage <> nil then
  begin
    Result := Trim(PortPage.Values[1]);
  end
  else
  begin
    Result := SelectInitialPort('TicketboxBackendPort', ExistingBackendPort, '8000', '8001');
  end;
end;

function GetDataRoot(Param: String): String;
begin
  Result := SelectedDataRoot();
end;

function GetPgPort(Param: String): String;
begin
  Result := SelectedPgPort();
end;

function GetBackendPort(Param: String): String;
begin
  Result := SelectedBackendPort();
end;

function FreshInstall(): Boolean;
begin
  Result := (not ExistingInstall) and (not DirExists(SelectedDataRoot() + '\pgdata'));
end;

function PortConflictMessage(): String;
var
  PgPort: String;
  BackendPort: String;
  BusyPorts: String;
begin
  Result := '';
  PgPort := SelectedPgPort();
  BackendPort := SelectedBackendPort();
  BusyPorts := '';

  if IsPortListening(PgPort) then
  begin
    BusyPorts := 'PostgreSQL 服务端口 ' + PgPort;
  end;
  if IsPortListening(BackendPort) then
  begin
    if BusyPorts <> '' then
    begin
      BusyPorts := BusyPorts + '、';
    end;
    BusyPorts := BusyPorts + '后端 API 端口 ' + BackendPort;
  end;

  if BusyPorts <> '' then
  begin
    Result :=
      '所选端口已被占用：' + BusyPorts + '。' + #13#10 + #13#10 +
      '请关闭占用这些端口的程序，或在上一步改用其它端口。开发机常用隔离端口：PostgreSQL 5440，后端 API 8001。';
  end;
end;

function FreshInstallPortError(): String;
begin
  Result := '';
  if FreshInstall() then
  begin
    Result := PortConflictMessage();
  end;
end;

procedure InitializeWizard();
begin
  LoadExistingConfig();

  DataRootPage := CreateInputDirPage(
    wpSelectDir,
    '选择小票夹数据目录',
    '数据库、上传图片、日志和备份会保存到这里。',
    '普通用户保持默认即可。开发机或想放到 D 盘时，可以在这里更改。',
    False,
    ''
  );
  DataRootPage.Add('数据目录');
  DataRootPage.Values[0] := SelectInitialDataRoot();

  PortPage := CreateInputQueryPage(
    DataRootPage.ID,
    '配置本机服务端口',
    '小票夹会安装 PostgreSQL 服务和后端 API 服务。',
    '普通用户保持默认即可；如果本机已有 PostgreSQL 或正在运行源码后端，请使用未被占用的端口。'
  );
  PortPage.Add('PostgreSQL 服务端口', False);
  PortPage.Add('后端 API 端口', False);
  PortPage.Values[0] := SelectInitialPort('TicketboxPgPort', ExistingPgPort, '5432', '5440');
  PortPage.Values[1] := SelectInitialPort('TicketboxBackendPort', ExistingBackendPort, '8000', '8001');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  MessageText: String;
begin
  Result := True;

  if CurPageID = DataRootPage.ID then
  begin
    if SelectedDataRoot() = '' then
    begin
      MsgBox('请选择数据目录。', mbError, MB_OK);
      Result := False;
      exit;
    end;

    if ExistingInstall and (ExistingDataRoot <> '') and (SelectedDataRoot() <> ExistingDataRoot) then
    begin
      MsgBox('升级安装暂不支持在安装器中迁移数据目录。请保持原数据目录：' + ExistingDataRoot, mbError, MB_OK);
      Result := False;
      exit;
    end;
  end;

  if CurPageID = PortPage.ID then
  begin
    if not IsValidPort(SelectedPgPort()) then
    begin
      MsgBox('PostgreSQL 服务端口必须是 1 到 65535 之间的数字。', mbError, MB_OK);
      Result := False;
      exit;
    end;
    if not IsValidPort(SelectedBackendPort()) then
    begin
      MsgBox('后端 API 端口必须是 1 到 65535 之间的数字。', mbError, MB_OK);
      Result := False;
      exit;
    end;
    if SelectedPgPort() = SelectedBackendPort() then
    begin
      MsgBox('PostgreSQL 服务端口和后端 API 端口不能相同。', mbError, MB_OK);
      Result := False;
      exit;
    end;

    if ExistingInstall then
    begin
      if (ExistingPgPort <> '') and (SelectedPgPort() <> ExistingPgPort) then
      begin
        MsgBox('升级安装暂不支持在安装器中修改 PostgreSQL 端口。请保持原端口：' + ExistingPgPort, mbError, MB_OK);
        Result := False;
        exit;
      end;
      if (ExistingBackendPort <> '') and (SelectedBackendPort() <> ExistingBackendPort) then
      begin
        MsgBox('升级安装暂不支持在安装器中修改后端 API 端口。请保持原端口：' + ExistingBackendPort, mbError, MB_OK);
        Result := False;
        exit;
      end;
    end;

    if FreshInstall() then
    begin
      MessageText := PortConflictMessage();
      if MessageText <> '' then
      begin
        MsgBox(MessageText, mbError, MB_OK);
        Result := False;
        exit;
      end;
    end;
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
      ' -DataRoot ' + Quote(SelectedDataRoot()) +
      ' -PgPort ' + SelectedPgPort() +
      ' -BackendPort ' + SelectedBackendPort();
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
