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
#define TicketboxMsvcRedistSource "..\..\..\backend\packaging\vendor\vc-runtime\vc_redist.x64.exe"
#define TicketboxRequiredMsvcRuntimeVersion GetVersionNumbersString(TicketboxMsvcRedistSource)

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
OutputBaseFilename=Ticketbox-Setup-{#AppVersion}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
Uninstallable=no

[Languages]
Name: "chinesesimp"; MessagesFile: "..\..\..\backend\packaging\languages\ChineseSimplified.isl"

[Files]
Source: "{#TicketboxMsvcRedistSource}"; DestDir: "{app}\bin"; DestName: "vc_redist.x64.exe"; Flags: ignoreversion
Source: "..\..\..\backend\dist\ticketbox-backend\*"; DestDir: "{app}\releases\{#ReleaseId}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\releases\{#ReleaseId}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\backend\packaging\vendor\pg\*"; DestDir: "{app}\postgresql"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\backend\packaging\vendor\shawl\shawl.exe"; DestDir: "{app}\bin"; DestName: "shawl.exe"; Flags: ignoreversion
Source: "..\payload\TicketboxLifecycle.exe"; DestDir: "{app}\bin"; DestName: "TicketboxLifecycle.exe"; Flags: ignoreversion
Source: "..\payload\release-manifest.json"; DestDir: "{app}\releases\{#ReleaseId}"; Flags: ignoreversion
Source: "..\..\..\backend\packaging\ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\小票夹\管理小票夹"; Filename: "{app}\releases\{#ReleaseId}\manager\ticketbox-manager.exe"; WorkingDir: "{app}\releases\{#ReleaseId}\manager"; IconFilename: "{app}\ticketbox.ico"

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"

[Code]
const
  TicketboxRequiredMsvcRuntimeVersion = '{#TicketboxRequiredMsvcRuntimeVersion}';

type
  TTicketboxGuid = record
    D1: LongWord;
    D2: Word;
    D3: Word;
    D4: array[0..7] of Byte;
  end;

var
  TicketboxProvisionOperationId: String;
  TicketboxPairingCode: String;
  TicketboxPairingExpiresAt: String;
  TicketboxRuntimeNeedsRestart: Boolean;

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
  Result := '';
  if CoCreateGuid(Guid) <> 0 then
    Exit;
  Result :=
    TicketboxToHex(Guid.D1, 8) + '-' +
    TicketboxToHex(Guid.D2, 4) + '-' +
    TicketboxToHex(Guid.D3, 4) + '-' +
    TicketboxToHex(Guid.D4[0], 2) + TicketboxToHex(Guid.D4[1], 2) + '-' +
    TicketboxToHex(Guid.D4[2], 2) + TicketboxToHex(Guid.D4[3], 2) +
    TicketboxToHex(Guid.D4[4], 2) + TicketboxToHex(Guid.D4[5], 2) +
    TicketboxToHex(Guid.D4[6], 2) + TicketboxToHex(Guid.D4[7], 2);
end;

function InitializeSetup: Boolean;
begin
  TicketboxProvisionOperationId := '';
  TicketboxPairingCode := '';
  TicketboxPairingExpiresAt := '';
  TicketboxRuntimeNeedsRestart := False;
  Result := True;
end;

function NeedRestart: Boolean;
begin
  Result := TicketboxRuntimeNeedsRestart;
end;

function TicketboxJsonString(const Text, Key: String): String;
var
  Needle, Rest: String;
  P, Q: Integer;
begin
  Result := '';
  Needle := '"' + Key + '": "';
  P := Pos(Needle, Text);
  if P = 0 then
  begin
    Needle := '"' + Key + '":"';
    P := Pos(Needle, Text);
  end;
  if P = 0 then
    Exit;
  Rest := Copy(Text, P + Length(Needle), 1000);
  Q := Pos('"', Rest);
  if Q > 1 then
    Result := Copy(Rest, 1, Q - 1);
end;

function TicketboxActiveOperationIsResumable: Boolean;
var
  ActivePath: String;
  Text: AnsiString;
  OperationId, Phase: String;
begin
  Result := False;
  ActivePath := ExpandConstant('{commonappdata}\Ticketbox\machine\operations\active.json');
  if not LoadStringFromFile(ActivePath, Text) then
    Exit;
  OperationId := TicketboxJsonString(String(Text), 'operation_id');
  Phase := TicketboxJsonString(String(Text), 'phase');
  Result := (OperationId <> '') and (Phase <> 'committed');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BindingPath: String;
begin
  { Read-only preflight. All mutation happens after complete [Files]. }
  NeedsRestart := False;
  Result := '';
  if not IsWin64 then
  begin
    Result := '小票夹需要 64 位 Windows。';
    Exit;
  end;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if FileExists(BindingPath) and (not TicketboxActiveOperationIsResumable()) then
  begin
    Result := '这台电脑已经安装小票夹。首次安装不会覆盖现有数据。';
    Exit;
  end;
end;

procedure TicketboxInstallMsvcRuntime;
var
  Redist, RuntimePath: String;
  ResultCode: Integer;
  InstalledVersion, RequiredVersion: Int64;
begin
  Redist := ExpandConstant('{app}\bin\vc_redist.x64.exe');
  if not FileExists(Redist) then
    RaiseException('小票夹安装失败：安装包缺少 Visual C++ 运行库。');
  if not Exec(Redist, '/install /quiet /norestart', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode) then
    RaiseException('小票夹安装失败：无法启动 Visual C++ 运行库安装。');
  if ResultCode = 3010 then
    TicketboxRuntimeNeedsRestart := True
  else if (ResultCode <> 0) and (ResultCode <> 1638) then
    RaiseException('小票夹安装失败：Visual C++ 运行库返回 ' +
      IntToStr(ResultCode) + '。');
  RuntimePath := ExpandConstant('{sys}\VCRUNTIME140.dll');
  if not GetPackedVersion(RuntimePath, InstalledVersion) then
    RaiseException('小票夹安装失败：无法读取 Visual C++ 运行库版本。');
  if not StrToVersion(TicketboxRequiredMsvcRuntimeVersion, RequiredVersion) then
    RaiseException('小票夹安装失败：安装包内 Visual C++ 运行库版本无效。');
  if ComparePackedVersion(InstalledVersion, RequiredVersion) < 0 then
    RaiseException('小票夹安装失败：Visual C++ 运行库版本过旧（实际 ' +
      VersionToStr(InstalledVersion) + '，需要 ' +
      TicketboxRequiredMsvcRuntimeVersion + ' 或更高版本）。');
end;

function TicketboxResultPath: String;
begin
  Result := ExpandConstant('{tmp}\ticketbox-install-result.json');
end;

function TicketboxResultIsCommitted(const OperationId: String): Boolean;
var
  Text: AnsiString;
  Body, Observed: String;
begin
  Result := False;
  TicketboxPairingCode := '';
  TicketboxPairingExpiresAt := '';
  if not LoadStringFromFile(TicketboxResultPath, Text) then
    Exit;
  Body := String(Text);
  Observed := TicketboxJsonString(Body, 'operation_id');
  if (OperationId = '') or (Observed <> OperationId) then
    Exit;
  if (Pos('"schema": "ticketbox-lifecycle-result-v2"', Body) = 0) and
     (Pos('"schema":"ticketbox-lifecycle-result-v2"', Body) = 0) then
    Exit;
  if (Pos('"ok": false', Body) > 0) or (Pos('"ok":false', Body) > 0) then
    Exit;
  if (Pos('"ok": true', Body) = 0) and (Pos('"ok":true', Body) = 0) then
    Exit;
  if (Pos('"phase": "committed"', Body) = 0) and
     (Pos('"phase":"committed"', Body) = 0) then
    Exit;
  if (Pos('"installation_published": true', Body) = 0) and
     (Pos('"installation_published":true', Body) = 0) then
    Exit;
  TicketboxPairingCode := TicketboxJsonString(Body, 'pairing_code');
  TicketboxPairingExpiresAt := TicketboxJsonString(Body, 'pairing_expires_at');
  Result := (TicketboxPairingCode <> '') and (TicketboxPairingExpiresAt <> '');
end;

function TicketboxResultFailure: String;
var
  Text: AnsiString;
  Code, MessageText: String;
begin
  Result := '生命周期控制器没有返回可验证结果';
  if not LoadStringFromFile(TicketboxResultPath, Text) then
    Exit;
  Code := TicketboxJsonString(String(Text), 'code');
  MessageText := TicketboxJsonString(String(Text), 'message');
  if MessageText <> '' then
    Result := MessageText;
  if Code <> '' then
    Result := Result + '（' + Code + '）';
end;

function WriteFreshInstallRequest(const Command, OperationId, ManifestSha: String): Boolean;
var
  RequestPath, Payload: String;
begin
  RequestPath := ExpandConstant('{tmp}\ticketbox-install-request.json');
  Payload :=
    '{"schema":"ticketbox-lifecycle-request-v1",' +
    '"command":"' + Command + '",' +
    '"operation_id":"' + OperationId + '",' +
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
    '"release_manifest_sha256":"' + ManifestSha + '"}';
  StringChangeEx(Payload, '\', '/', True);
  Result := SaveStringToFile(RequestPath, Utf8Encode(Payload), False);
end;

function TicketboxLifecycleParams(Param: String): String;
var
  Command, OperationId, ActivePath, Existing, ManifestPath, ManifestSha: String;
  ActiveText: AnsiString;
begin
  Result := '';
  Command := 'install';
  OperationId := TicketboxNewUuid;
  if OperationId = '' then
    Exit;
  ActivePath := ExpandConstant('{commonappdata}\Ticketbox\machine\operations\active.json');
  if LoadStringFromFile(ActivePath, ActiveText) then
  begin
    Existing := TicketboxJsonString(String(ActiveText), 'operation_id');
    if Existing <> '' then
    begin
      OperationId := Existing;
      Command := 'resume';
    end;
  end;
  ManifestPath := ExpandConstant('{app}\releases\{#ReleaseId}\release-manifest.json');
  ManifestSha := GetSHA256OfFile(ManifestPath);
  if ManifestSha = '' then
    Exit;
  if not WriteFreshInstallRequest(Command, OperationId, ManifestSha) then
    Exit;
  TicketboxProvisionOperationId := OperationId;
  Result := Command + ' --request "' +
    ExpandConstant('{tmp}\ticketbox-install-request.json') + '" --result "' +
    TicketboxResultPath + '"';
end;

procedure TicketboxProvision;
var
  Params, Coordinator: String;
  ResultCode: Integer;
begin
  TicketboxInstallMsvcRuntime;
  Params := TicketboxLifecycleParams('');
  if Params = '' then
    RaiseException('小票夹安装失败：无法生成首次安装请求。');
  if FileExists(TicketboxResultPath) and (not DeleteFile(TicketboxResultPath)) then
    RaiseException('小票夹安装失败：无法清理上一次临时结果。');
  Coordinator := ExpandConstant('{app}\bin\TicketboxLifecycle.exe');
  if not Exec(Coordinator, Params, ExpandConstant('{app}\bin'), SW_HIDE,
      ewWaitUntilTerminated, ResultCode) then
    RaiseException('小票夹安装失败：无法启动生命周期控制器。');
  if (ResultCode <> 0) or
     (not TicketboxResultIsCommitted(TicketboxProvisionOperationId)) then
    RaiseException('小票夹首次安装没有完成：' + TicketboxResultFailure +
      '。请重新运行同一个安装包继续。');
  MsgBox('小票夹安装完成。' + #13#10 + #13#10 +
    '首次配对码：' + TicketboxPairingCode + #13#10 +
    '有效期至：' + TicketboxPairingExpiresAt + #13#10 + #13#10 +
    '请打开“管理小票夹”完成设备绑定。', mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { Official topic_installorder and topic_scriptevents define ssPostInstall
    after complete
    materialization. We do not use a [Files] AfterInstall callback because
    NotifyAfterInstallEntry does not propagate its exception as this owner. }
  if CurStep = ssPostInstall then
    TicketboxProvision;
end;
