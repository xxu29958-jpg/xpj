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
Source: "..\payload\release-manifest.json"; DestDir: "{app}\releases\{#ReleaseId}"; Flags: ignoreversion; AfterInstall: TicketboxProvision
Source: "..\..\..\backend\packaging\ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\小票夹\管理小票夹"; Filename: "{app}\releases\{#ReleaseId}\manager\ticketbox-manager.exe"; WorkingDir: "{app}\releases\{#ReleaseId}\manager"; IconFilename: "{app}\ticketbox.ico"

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallIdPending"; ValueData: "projection-only"; Flags: uninsdeletevalue

; Official Inno [Run] waits for the process but does not check its exit code, and
; runs after uninstaller finalize (jrsoftware ishelp topic_runsection). Official
; AfterInstall exceptions are swallowed in jrsoftware issrc Projects/Main.pas
; NotifyAfterInstallEntry (HandleException; install continues). /VERYSILENT
; /SUPPRESSMSGBOXES then defaults that dialog to OK, so Setup.exe can still
; return 0. Coordinator therefore runs from the last payload [Files]
; AfterInstall via Exec; GetCustomSetupExitCode (jrsoftware ishelp
; topic_scriptevents) overlays a non-zero exit when last-result is not this
; operation's committed success. Files may remain; that is staged material, not
; a committed installation.

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

var
  TicketboxProvisionResultCode: Integer;
  TicketboxProvisionOperationId: String;

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
  TicketboxProvisionResultCode := -1;
  TicketboxProvisionOperationId := '';
  Result := True;
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
  Rest := Copy(Text, P + Length(Needle), 500);
  Q := Pos('"', Rest);
  if Q > 1 then
    Result := Copy(Rest, 1, Q - 1);
end;

function TicketboxResultIsCommitted(ResultCode: Integer; const OperationId: String): Boolean;
var
  ResultPath, Observed: String;
  Text: AnsiString;
begin
  Result := False;
  ResultPath := ExpandConstant('{commonappdata}\Ticketbox\machine\operations\last-result.json');
  if ResultCode <> 0 then
    Exit;
  if not LoadStringFromFile(ResultPath, Text) then
    Exit;
  Observed := TicketboxJsonString(String(Text), 'operation_id');
  if (OperationId = '') or (Observed <> OperationId) then
    Exit;
  if (Pos('"ok": false', String(Text)) > 0) or (Pos('"ok":false', String(Text)) > 0) then
    Exit;
  if (Pos('"ok": true', String(Text)) = 0) and (Pos('"ok":true', String(Text)) = 0) then
    Exit;
  if (Pos('"phase": "committed"', String(Text)) = 0) and (Pos('"phase":"committed"', String(Text)) = 0) then
    Exit;
  Result := True;
end;

function GetCustomSetupExitCode: Integer;
begin
  { Official: only called when Inno would otherwise return 0. AfterInstall
    exceptions cannot fail Setup; this overlay is the documented success-path
    custom exit. }
  if TicketboxResultIsCommitted(TicketboxProvisionResultCode, TicketboxProvisionOperationId) then
    Result := 0
  else
    Result := 1;
end;

function WriteFreshInstallRequest(const Command, OperationId, ManifestSha: String): Boolean;
var
  RequestPath: String;
  Payload: String;
begin
  Result := False;
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
  Result := SaveStringToFile(RequestPath, AnsiString(Payload), False);
end;

procedure TicketboxProvision;
var
  ResultCode: Integer;
  Lifecycle: String;
  Params: String;
  Command: String;
  OperationId: String;
  ActivePath: String;
  ActiveText: AnsiString;
  Existing: String;
  ManifestPath: String;
  ManifestSha: String;
begin
  TicketboxProvisionResultCode := -1;
  TicketboxProvisionOperationId := '';
  Command := 'install';
  OperationId := TicketboxNewUuid;
  if OperationId = '' then
  begin
    Log('Ticketbox provision: could not allocate operation_id');
    Exit;
  end;
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
  TicketboxProvisionOperationId := OperationId;
  ManifestPath := ExpandConstant('{app}\releases\{#ReleaseId}\release-manifest.json');
  ManifestSha := GetSHA256OfFile(ManifestPath);
  if ManifestSha = '' then
  begin
    Log('Ticketbox provision: release-manifest SHA-256 is empty');
    Exit;
  end;
  if not WriteFreshInstallRequest(Command, OperationId, ManifestSha) then
  begin
    Log('Ticketbox provision: could not write install request');
    Exit;
  end;
  Lifecycle := ExpandConstant('{app}\bin\TicketboxLifecycle.exe');
  Params :=
    Command + ' --request "' + ExpandConstant('{tmp}\ticketbox-install-request.json') +
    '" --result "' + ExpandConstant('{commonappdata}\Ticketbox\machine\operations\last-result.json') + '"';
  if not Exec(Lifecycle, Params, ExpandConstant('{app}\bin'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('Ticketbox provision: could not start TicketboxLifecycle.exe');
    TicketboxProvisionResultCode := 1;
    Exit;
  end;
  TicketboxProvisionResultCode := ResultCode;
  if not TicketboxResultIsCommitted(ResultCode, OperationId) then
    Log('Ticketbox provision: last-result is not this operation committed');
end;
