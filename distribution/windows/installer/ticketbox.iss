#ifndef AppVersion
#define AppVersion "0.0.0-dev"
#endif
#ifndef ReleaseId
#define ReleaseId AppVersion
#endif
#ifndef PgServiceName
#define PgServiceName "TicketboxPg"
#endif
#ifndef BackendServiceName
#define BackendServiceName "TicketboxBackend"
#endif
#ifndef DefaultPgPort
#define DefaultPgPort "5432"
#endif
#ifndef DefaultBackendPort
#define DefaultBackendPort "8000"
#endif

[Setup]
AppId={{A9E0C4D2-7B11-4F20-9C6A-2D8F1B0A4E77}}
AppName=小票夹
AppVersion={#AppVersion}
AppPublisher=Ticketbox
DefaultDirName={autopf}\Ticketbox
DefaultGroupName=小票夹
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=小票夹
OutputBaseFilename=Ticketbox-Setup-{#AppVersion}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "..\..\..\backend\packaging\languages\ChineseSimplified.isl"

[Files]
Source: "..\..\..\backend\packaging\vendor\vc-runtime\vc_redist.x64.exe"; DestName: "vc_redist.x64.exe"; Flags: dontcopy noencryption
Source: "..\..\..\backend\dist\ticketbox-backend\*"; DestDir: "{app}\releases\{#ReleaseId}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\releases\{#ReleaseId}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\backend\packaging\vendor\pg\*"; DestDir: "{app}\postgresql"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\backend\packaging\vendor\shawl\shawl.exe"; DestDir: "{app}\bin"; DestName: "shawl.exe"; Flags: ignoreversion
Source: "..\payload\TicketboxLifecycle.exe"; DestDir: "{app}\bin"; DestName: "TicketboxLifecycle.exe"; Flags: ignoreversion
Source: "..\payload\TicketboxBackendLauncher.exe"; DestDir: "{app}\bin"; DestName: "TicketboxBackendLauncher.exe"; Flags: ignoreversion
Source: "..\payload\release-manifest.json"; DestDir: "{app}\releases\{#ReleaseId}"; Flags: ignoreversion
Source: "..\..\..\backend\packaging\ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\小票夹\管理小票夹"; Filename: "{app}\releases\{#ReleaseId}\manager\ticketbox-manager.exe"; WorkingDir: "{app}\releases\{#ReleaseId}\manager"; IconFilename: "{app}\ticketbox.ico"

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallIdPending"; ValueData: "projection-only"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\bin\TicketboxLifecycle.exe"; Parameters: "install --request ""{tmp}\ticketbox-install-request.json"" --result ""{commonappdata}\Ticketbox\machine\operations\last-result.json"""; StatusMsg: "正在完成小票夹首次配置…"; Flags: runhidden waituntilterminated; BeforeInstall: WriteFreshInstallRequest

[UninstallDelete]
Type: filesandordirs; Name: "{app}\releases"
Type: filesandordirs; Name: "{app}\bin"

[Code]
type
  TTicketboxGuid = record
    D1: LongWord;
    D2: Word;
    D3: Word;
    D4: array[0..7] of Byte;
  end;

function CoCreateGuid(var Guid: TTicketboxGuid): Integer;
external 'CoCreateGuid@ole32.dll stdcall';

function TicketboxHexDigit(Value: Integer): String;
begin
  Result := Copy('0123456789abcdef', (Value and $F) + 1, 1);
end;

function TicketboxToHex(Value: LongWord; Digits: Integer): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Digits do
  begin
    Result := TicketboxHexDigit(Value) + Result;
    Value := Value shr 4;
  end;
end;

function TicketboxNewUuid: String;
var
  Guid: TTicketboxGuid;
begin
  if CoCreateGuid(Guid) <> 0 then
    RaiseException('无法生成 operation_id。');
  Result :=
    TicketboxToHex(Guid.D1, 8) + '-' +
    TicketboxToHex(Guid.D2, 4) + '-' +
    TicketboxToHex(Guid.D3, 4) + '-' +
    TicketboxToHex(Guid.D4[0], 2) + TicketboxToHex(Guid.D4[1], 2) + '-' +
    TicketboxToHex(Guid.D4[2], 2) + TicketboxToHex(Guid.D4[3], 2) +
    TicketboxToHex(Guid.D4[4], 2) + TicketboxToHex(Guid.D4[5], 2) +
    TicketboxToHex(Guid.D4[6], 2) + TicketboxToHex(Guid.D4[7], 2);
end;

function TicketboxMsvcRuntimePresent: Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\VCRUNTIME140.dll'));
end;

function TicketboxEnsureMsvcRuntime(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Redist: String;
begin
  Result := '';
  if TicketboxMsvcRuntimePresent then
    exit;
  ExtractTemporaryFile('vc_redist.x64.exe');
  Redist := ExpandConstant('{tmp}\vc_redist.x64.exe');
  if not Exec(Redist, '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := '无法启动 Visual C++ 运行库安装。';
    exit;
  end;
  if TicketboxMsvcRuntimePresent then
    exit;
  if ResultCode = 3010 then
  begin
    NeedsRestart := True;
    exit;
  end;
  if (ResultCode <> 0) and (ResultCode <> 1638) then
    Result := 'Visual C++ 运行库安装失败（exit=' + IntToStr(ResultCode) + '）。'
  else
    Result := 'Visual C++ 运行库安装后仍检测不到 VCRUNTIME140.dll。';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BindingPath: String;
begin
  NeedsRestart := False;
  Result := '';
  if not IsWin64 then
  begin
    Result := '小票夹需要 64 位 Windows。';
    exit;
  end;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if FileExists(BindingPath) then
  begin
    Result := '此计算机已有 Ticketbox installation.json。首次安装不会覆盖数据身份。';
    exit;
  end;
  Result := TicketboxEnsureMsvcRuntime(NeedsRestart);
end;

procedure WriteFreshInstallRequest;
var
  RequestPath: String;
  Payload: String;
begin
  RequestPath := ExpandConstant('{tmp}\ticketbox-install-request.json');
  Payload :=
    '{"schema":"ticketbox-lifecycle-request-v1",' +
    '"operation_id":"' + TicketboxNewUuid + '",' +
    '"request_hash":"pending",' +
    '"target_release_id":"{#ReleaseId}",' +
    '"app_dir":"' + ExpandConstant('{app}') + '",' +
    '"data_root":"' + ExpandConstant('{commonappdata}\Ticketbox\data') + '",' +
    '"program_data_root":"' + ExpandConstant('{commonappdata}\Ticketbox') + '",' +
    '"pg_service_name":"{#PgServiceName}",' +
    '"backend_service_name":"{#BackendServiceName}",' +
    '"pg_port":{#DefaultPgPort},' +
    '"backend_port":{#DefaultBackendPort},' +
    '"postgres_major":17,' +
    '"release_manifest_sha256":"pending"}';
  StringChangeEx(Payload, '\', '/', True);
  if not SaveStringToFile(RequestPath, Payload, False) then
    RaiseException('无法写入 fresh-install request。');
end;
