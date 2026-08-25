#ifndef AppVersion
#define AppVersion "0.0.0-dev"
#endif
#ifndef ReleaseId
#define ReleaseId AppVersion
#endif
#ifndef ReleaseManifestSha256
#define ReleaseManifestSha256 "pending"
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
DisableDirPage=yes
UsePreviousAppDir=no
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
CloseApplications=no
RestartApplications=no
Uninstallable=no

[Languages]
Name: "chinesesimp"; MessagesFile: "..\..\..\backend\packaging\languages\ChineseSimplified.isl"

[Files]
Source: "{#TicketboxMsvcRedistSource}"; DestDir: "{app}\bin"; DestName: "vc_redist.x64.exe"; Flags: ignoreversion
Source: "..\..\..\backend\dist\ticketbox-backend\*"; DestDir: "{app}\releases\{#ReleaseId}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "..\..\..\backend\dist\ticketbox-backend\*"; DestDir: "{app}\releases\{#ReleaseId}\backend"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "..\..\..\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\releases\{#ReleaseId}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "..\..\..\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\releases\{#ReleaseId}\manager"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "..\..\..\backend\packaging\vendor\pg\*"; DestDir: "{app}\postgresql"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "..\..\..\backend\packaging\vendor\pg\*"; DestDir: "{app}\postgresql"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "..\..\..\backend\packaging\vendor\shawl\shawl.exe"; DestDir: "{app}\bin"; DestName: "shawl.exe"; Flags: ignoreversion; Check: TicketboxFreshMaterialization
Source: "..\..\..\backend\packaging\vendor\shawl\shawl.exe"; DestDir: "{app}\bin"; DestName: "shawl.exe"; Flags: ignoreversion onlyifdoesntexist; Check: TicketboxExactResumeMaterialization
Source: "..\payload\TicketboxLifecycle\*"; DestDir: "{app}\bin\lifecycle"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\payload\release-manifest.json"; DestDir: "{app}\releases\{#ReleaseId}"; Flags: ignoreversion
Source: "..\..\..\backend\packaging\ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\小票夹\管理小票夹"; Filename: "{app}\releases\{#ReleaseId}\manager\ticketbox-manager.exe"; WorkingDir: "{app}\releases\{#ReleaseId}\manager"; IconFilename: "{app}\ticketbox.ico"

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"

[Run]
Filename: "{app}\bin\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; WorkingDir: "{app}\bin"; StatusMsg: "正在安装 Visual C++ 运行库..."; Flags: runhidden waituntilterminated
Filename: "{app}\bin\lifecycle\TicketboxLifecycle.exe"; Parameters: "{code:TicketboxLifecycleParams}"; WorkingDir: "{app}\bin\lifecycle"; StatusMsg: "正在完成小票夹首次安装..."; Flags: runhidden waituntilterminated

[Code]
const
  TicketboxRequiredMsvcRuntimeVersion = '{#TicketboxRequiredMsvcRuntimeVersion}';
  TicketboxExpectedReleaseManifestSha256 = '{#ReleaseManifestSha256}';

var
  TicketboxProvisionOperationId: String;
  TicketboxPairingCode: String;
  TicketboxPairingExpiresAt: String;
  TicketboxInstallFailed: Boolean;
  TicketboxInstallFailureReason: String;

function InitializeSetup: Boolean;
begin
  TicketboxProvisionOperationId := '';
  TicketboxPairingCode := '';
  TicketboxPairingExpiresAt := '';
  TicketboxInstallFailed := False;
  TicketboxInstallFailureReason := '';
  Result := True;
end;

procedure TicketboxMarkInstallFailed(const Reason: String);
begin
  TicketboxInstallFailed := True;
  TicketboxInstallFailureReason := Reason;
  Log('Ticketbox install failed: ' + Reason);
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

function TicketboxOperationId: String;
begin
  Result := 'fresh-{#ReleaseManifestSha256}';
end;

function TicketboxActivePath: String;
begin
  Result := ExpandConstant('{commonappdata}\Ticketbox\machine\operations\active.json');
end;

function TicketboxCommittedHistoryPath: String;
begin
  Result := ExpandConstant('{commonappdata}\Ticketbox\machine\operations\history\') +
    TicketboxOperationId + '.json';
end;

function TicketboxOperationMatches(const Path, RequiredPhase: String): Boolean;
var
  Text: AnsiString;
  Body: String;
begin
  Result := False;
  if not LoadStringFromFile(Path, Text) then
    Exit;
  Body := String(Text);
  Result :=
    (TicketboxJsonString(Body, 'operation_id') = TicketboxOperationId) and
    (TicketboxJsonString(Body, 'target_release_id') = '{#ReleaseId}') and
    (TicketboxJsonString(Body, 'release_manifest_sha256') =
      TicketboxExpectedReleaseManifestSha256);
  if Result and (RequiredPhase <> '') then
    Result := TicketboxJsonString(Body, 'phase') = RequiredPhase;
end;

function TicketboxExactActiveCanContinue: Boolean;
begin
  Result := TicketboxOperationMatches(TicketboxActivePath, '');
end;

function TicketboxCommittedReplayCanContinue: Boolean;
var
  BindingPath: String;
  BindingText: AnsiString;
  Body: String;
begin
  Result := False;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if not LoadStringFromFile(BindingPath, BindingText) then
    Exit;
  Body := String(BindingText);
  Result :=
    (TicketboxJsonString(Body, 'active_release_id') = '{#ReleaseId}') and
    (TicketboxJsonString(Body, 'release_manifest_sha256') =
      TicketboxExpectedReleaseManifestSha256) and
    TicketboxOperationMatches(TicketboxCommittedHistoryPath, 'committed');
end;

function TicketboxExactResumeMaterialization: Boolean;
begin
  Result := TicketboxExactActiveCanContinue or TicketboxCommittedReplayCanContinue;
end;

function TicketboxFreshMaterialization: Boolean;
begin
  Result := not TicketboxExactResumeMaterialization;
end;

function TicketboxInstallRootIsExact: Boolean;
var
  ActualPath, ExpectedPath: String;
begin
  ActualPath := RemoveBackslashUnlessRoot(ExpandFileName(ExpandConstant('{app}')));
  ExpectedPath := RemoveBackslashUnlessRoot(
    ExpandFileName(ExpandConstant('{autopf}\Ticketbox')));
  Result := CompareText(ActualPath, ExpectedPath) = 0;
end;

function TicketboxPrepareFailure(const Reason: String): String;
begin
  Log('Ticketbox preflight failed: ' + Reason);
  Result := Reason + '。' + #13#10 +
    '请关闭安装程序，处理上述问题后重新运行同一个安装包。' + #13#10 +
    '安装日志：' + ExpandConstant('{log}');
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
    Result := TicketboxPrepareFailure('小票夹需要 64 位 Windows');
    Exit;
  end;
  if not TicketboxInstallRootIsExact then
  begin
    Result := TicketboxPrepareFailure('安装目录必须是受保护的 Program Files\Ticketbox');
    Exit;
  end;
  if Length(TicketboxExpectedReleaseManifestSha256) <> 64 then
  begin
    Result := TicketboxPrepareFailure('安装包缺少 immutable release manifest 身份');
    Exit;
  end;
  if FileExists(TicketboxActivePath) and (not TicketboxExactActiveCanContinue()) then
  begin
    Result := TicketboxPrepareFailure('检测到另一个或损坏的首次安装操作；拒绝接管');
    Exit;
  end;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if FileExists(BindingPath) and (not TicketboxCommittedReplayCanContinue()) and
     (not TicketboxExactActiveCanContinue()) then
  begin
    Result := TicketboxPrepareFailure('这台电脑已经安装小票夹；首次安装不会覆盖现有数据');
    Exit;
  end;
end;

function TicketboxMsvcRuntimeIsCurrent(var Reason: String): Boolean;
var
  RuntimePath: String;
  InstalledVersion, RequiredVersion: Int64;
begin
  Result := False;
  Reason := '';
  RuntimePath := ExpandConstant('{sys}\VCRUNTIME140.dll');
  if not GetPackedVersion(RuntimePath, InstalledVersion) then
  begin
    Reason := '无法读取 Visual C++ 运行库版本';
    Exit;
  end;
  if not StrToVersion(TicketboxRequiredMsvcRuntimeVersion, RequiredVersion) then
  begin
    Reason := '安装包内 Visual C++ 运行库版本无效';
    Exit;
  end;
  if ComparePackedVersion(InstalledVersion, RequiredVersion) < 0 then
  begin
    Reason := 'Visual C++ 运行库版本过旧（实际 ' +
      VersionToStr(InstalledVersion) + '，需要 ' +
      TicketboxRequiredMsvcRuntimeVersion + ' 或更高版本）';
    Exit;
  end;
  Result := True;
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
  Code: String;
begin
  Result := '生命周期控制器没有返回可验证结果';
  if not LoadStringFromFile(TicketboxResultPath, Text) then
    Exit;
  Code := TicketboxJsonString(String(Text), 'code');
  if Code <> '' then
    Result := '生命周期控制器报告失败（错误代码：' + Code + '）';
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
  Command, OperationId, ManifestPath, ManifestSha: String;
begin
  Result := '';
  if FileExists(TicketboxResultPath) and (not DeleteFile(TicketboxResultPath)) then
  begin
    TicketboxMarkInstallFailed('无法清理上一次临时结果');
    Exit;
  end;
  Command := 'install';
  OperationId := TicketboxOperationId;
  if TicketboxExactResumeMaterialization then
    Command := 'resume';
  ManifestPath := ExpandConstant('{app}\releases\{#ReleaseId}\release-manifest.json');
  ManifestSha := LowerCase(GetSHA256OfFile(ManifestPath));
  if (ManifestSha = '') or
     (ManifestSha <> LowerCase(TicketboxExpectedReleaseManifestSha256)) then
  begin
    TicketboxMarkInstallFailed('无法验证已发布的 release-manifest.json');
    Exit;
  end;
  if not WriteFreshInstallRequest(Command, OperationId, ManifestSha) then
  begin
    TicketboxMarkInstallFailed('无法生成首次安装请求');
    Exit;
  end;
  TicketboxProvisionOperationId := OperationId;
  Result := Command + ' --request "' +
    ExpandConstant('{tmp}\ticketbox-install-request.json') + '" --result "' +
    TicketboxResultPath + '"';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Reason: String;
begin
  if CurStep = ssPostInstall then
  begin
    { ssPostInstall only observes the completed [Run] postconditions. }
    if (not TicketboxInstallFailed) and
       (not TicketboxMsvcRuntimeIsCurrent(Reason)) then
      TicketboxMarkInstallFailed(Reason);
    if (not TicketboxInstallFailed) and
       (not TicketboxResultIsCommitted(TicketboxProvisionOperationId)) then
      TicketboxMarkInstallFailed(TicketboxResultFailure);
    if TicketboxInstallFailed then
      SuppressibleMsgBox('小票夹安装未完成：' + TicketboxInstallFailureReason + '。' + #13#10 +
        '请重新运行同一个安装包继续。' + #13#10 +
        '安装日志：' + ExpandConstant('{log}'), mbError, MB_OK, IDOK)
    else
      SuppressibleMsgBox('小票夹安装完成。' + #13#10 + #13#10 +
        '首次配对码：' + TicketboxPairingCode + #13#10 +
        '有效期至：' + TicketboxPairingExpiresAt + #13#10 + #13#10 +
        '请打开“管理小票夹”完成设备绑定。', mbInformation, MB_OK, IDOK);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and TicketboxInstallFailed then
  begin
    WizardForm.FinishedHeadingLabel.Caption := '小票夹安装未完成';
    WizardForm.FinishedLabel.Caption := TicketboxInstallFailureReason + '。' + #13#10 +
      '请关闭安装程序，然后重新运行同一个安装包继续。' + #13#10 +
      '安装日志：' + ExpandConstant('{log}');
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if TicketboxInstallFailed then
    Result := 1
  else
    Result := 0;
end;
