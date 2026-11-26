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
; Resolve the snapshot root before Inno 6 opens deeply nested payload files.
#define TicketboxRepositorySource ExtractFileDir(ExtractFileDir(ExtractFileDir(RemoveBackslashUnlessRoot(SourcePath))))
#define TicketboxMsvcRedistSource TicketboxRepositorySource + "\backend\packaging\vendor\vc-runtime\vc_redist.x64.exe"
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
SetupIconFile={#TicketboxRepositorySource}\backend\packaging\ticketbox.ico
OutputBaseFilename=Ticketbox-Setup-{#AppVersion}
SetupLogging=yes
CloseApplications=no
RestartApplications=no
Uninstallable=yes
UninstallFilesDir={commoncf64}\Ticketbox\uninstall
CreateUninstallRegKey=yes
UninstallDisplayName=小票夹
UninstallDisplayIcon={app}\ticketbox.ico

[Languages]
Name: "chinesesimp"; MessagesFile: "{#TicketboxRepositorySource}\backend\packaging\languages\ChineseSimplified.isl"

[Files]
Source: "{#TicketboxMsvcRedistSource}"; DestDir: "{app}\bin"; DestName: "vc_redist.x64.exe"; Flags: ignoreversion; Check: TicketboxDirectSharedMaterialization
Source: "{#TicketboxRepositorySource}\backend\dist\ticketbox-backend\*"; DestDir: "{app}\releases\{#ReleaseId}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\backend\dist\ticketbox-backend\*"; DestDir: "{app}\releases\{#ReleaseId}\backend"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\releases\{#ReleaseId}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\releases\{#ReleaseId}\manager"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\cloudflared\*"; DestDir: "{app}\releases\{#ReleaseId}\connector"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\cloudflared\*"; DestDir: "{app}\releases\{#ReleaseId}\connector"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\TicketboxLifecycle\*"; DestDir: "{app}\releases\{#ReleaseId}\lifecycle"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\TicketboxLifecycle\*"; DestDir: "{app}\releases\{#ReleaseId}\lifecycle"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\pg\*"; DestDir: "{app}\postgresql"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\pg\*"; DestDir: "{app}\postgresql"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\shawl\shawl.exe"; DestDir: "{app}\bin"; DestName: "shawl.exe"; Flags: ignoreversion; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\shawl\shawl.exe"; DestDir: "{app}\bin"; DestName: "shawl.exe"; Flags: ignoreversion onlyifdoesntexist; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\TicketboxLifecycle\*"; DestDir: "{app}\bin\lifecycle"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxDirectSharedMaterialization
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\release-manifest.json"; DestDir: "{app}\releases\{#ReleaseId}"; Flags: ignoreversion; Check: TicketboxFreshMaterialization
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\release-manifest.json"; DestDir: "{app}\releases\{#ReleaseId}"; Flags: ignoreversion onlyifdoesntexist; Check: TicketboxExactResumeMaterialization
Source: "{#TicketboxRepositorySource}\backend\packaging\ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion; Check: TicketboxDirectSharedMaterialization
Source: "{#TicketboxMsvcRedistSource}"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\_staging"; DestName: "vc_redist.x64.exe"; Flags: ignoreversion; Check: TicketboxUpgradeStageReady
Source: "{#TicketboxRepositorySource}\backend\packaging\ticketbox.ico"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\_staging"; Flags: ignoreversion; Check: TicketboxUpgradeStageReady
Source: "{#TicketboxRepositorySource}\backend\dist\ticketbox-backend\*"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxUpgradeStageReady
Source: "{#TicketboxRepositorySource}\desktop\dist\ticketbox-manager\*"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxUpgradeStageReady
Source: "{#TicketboxRepositorySource}\backend\packaging\vendor\cloudflared\*"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\connector"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxUpgradeStageReady
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\TicketboxLifecycle\*"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\lifecycle"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxUpgradeStageReady
Source: "{#TicketboxRepositorySource}\distribution\windows\payload\release-manifest.json"; DestDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}"; Flags: ignoreversion; Check: TicketboxUpgradeStageReady

[Icons]
; AppUserModelID must equal backend_manager.desktop_shell.MANAGER_APP_ID: the Manager's
; Edge window carries it, so Windows groups and pins that window under this shortcut.
Name: "{autoprograms}\小票夹\管理小票夹"; Filename: "{app}\releases\{#ReleaseId}\manager\ticketbox-manager.exe"; WorkingDir: "{app}\releases\{#ReleaseId}\manager"; IconFilename: "{app}\ticketbox.ico"; AppUserModelID: "Ticketbox.Manager"; Check: TicketboxDirectSharedMaterialization

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Check: TicketboxDirectSharedMaterialization

[Run]
Filename: "{app}\bin\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; WorkingDir: "{app}\bin"; StatusMsg: "正在安装 Visual C++ 运行库..."; Flags: runhidden waituntilterminated; Check: TicketboxDirectSharedMaterialization
Filename: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\_staging\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; WorkingDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\_staging"; StatusMsg: "正在安装 Visual C++ 运行库..."; Flags: runhidden waituntilterminated; Check: TicketboxUpgradeNeedsVcRedist
Filename: "{app}\bin\lifecycle\TicketboxLifecycle.exe"; Parameters: "{code:TicketboxLifecycleParams}"; WorkingDir: "{app}\bin\lifecycle"; StatusMsg: "正在完成小票夹受控生命周期操作..."; Flags: runhidden waituntilterminated logoutput; Check: TicketboxDirectSharedMaterialization
Filename: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\lifecycle\TicketboxLifecycle.exe"; Parameters: "{code:TicketboxLifecycleParams}"; WorkingDir: "{autopf}\Ticketbox-UpgradeStage\{#ReleaseId}\lifecycle"; StatusMsg: "正在完成小票夹受管升级..."; Flags: runhidden waituntilterminated logoutput; Check: TicketboxUpgradeStageReady

[Code]
const
  TicketboxRequiredMsvcRuntimeVersion = '{#TicketboxRequiredMsvcRuntimeVersion}';
  TicketboxExpectedReleaseManifestSha256 = '{#ReleaseManifestSha256}';
  TicketboxFileFlagOpenReparsePoint = $00200000; { FILE_FLAG_OPEN_REPARSE_POINT }
  TicketboxFileFlagBackupSemantics = $02000000; { FILE_FLAG_BACKUP_SEMANTICS }
  TicketboxProtectedDaclSecurityInformation = $80000000;

type
  TTicketboxSecurityAttributes = record
    nLength: LongWord;
    lpSecurityDescriptor: LongWord;
    bInheritHandle: LongWord;
  end;
  TTicketboxFileAttributeTagInfo = record
    FileAttributes: LongWord;
    ReparseTag: LongWord;
  end;
  TTicketboxAclSizeInformation = record
    AceCount: LongWord;
    AclBytesInUse: LongWord;
    AclBytesFree: LongWord;
  end;

var
  TicketboxProvisionOperationId: String;
  TicketboxPairingCode: String;
  TicketboxPairingExpiresAt: String;
  TicketboxInstallFailed: Boolean;
  TicketboxInstallFailureReason: String;
  TicketboxUpgradeRolledBack: Boolean;
  TicketboxRestoredReleaseId: String;
  TicketboxRestoreModeResult: String;
  TicketboxReconnectGuidance: String;
  TicketboxSetupLeaseHandle: LongWord;
  TicketboxResultDirectoryHandle: LongWord;
  TicketboxUpgradeStageOwned: Boolean;

#include "setup_security.iss"
#include "setup_lease.iss"
#include "setup_private_result.iss"

function InitializeSetup: Boolean;
begin
  TicketboxProvisionOperationId := '';
  TicketboxPairingCode := '';
  TicketboxPairingExpiresAt := '';
  TicketboxInstallFailed := False;
  TicketboxInstallFailureReason := '';
  TicketboxUpgradeRolledBack := False;
  TicketboxRestoredReleaseId := '';
  TicketboxRestoreModeResult := '';
  TicketboxReconnectGuidance := '';
  TicketboxSetupLeaseHandle := 0;
  TicketboxResultDirectoryHandle := 0;
  TicketboxUpgradeStageOwned := False;
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

function TicketboxRestoreRequested: Boolean;
begin
  Result := ExpandConstant('{param:RESTORECOPY|}') <> '';
end;

function TicketboxRestoreMode: String;
var
  RawMode: String;
begin
  RawMode := LowerCase(Trim(ExpandConstant('{param:RESTOREMODE|same-environment}')));
  if RawMode = '' then
    RawMode := 'same-environment';
  Result := RawMode;
end;

function TicketboxUpgradeRequested: Boolean;
var
  ParamValue: String;
begin
  ParamValue := UpperCase(ExpandConstant('{param:UPGRADE|}'));
  Result := (ParamValue = 'YES') or (ParamValue = '1') or (ParamValue = 'TRUE');
end;

function TicketboxUpgradeRollbackDisabled: Boolean;
var
  ParamValue: String;
begin
  ParamValue := UpperCase(ExpandConstant('{param:NOROLLBACK|}'));
  Result := (ParamValue = 'YES') or (ParamValue = '1') or (ParamValue = 'TRUE');
end;

function TicketboxReinstallRequested: Boolean;
var
  ParamValue: String;
begin
  ParamValue := UpperCase(ExpandConstant('{param:REINSTALL|}'));
  Result := (ParamValue = 'YES') or (ParamValue = '1') or (ParamValue = 'TRUE');
end;

function TicketboxOperationId: String;
begin
  Result := 'fresh-{#ReleaseManifestSha256}';
  if TicketboxRestoreRequested then
    Result := 'restore-{#ReleaseManifestSha256}'
  else if TicketboxUpgradeRequested then
    Result := 'upgrade-{#ReleaseManifestSha256}'
  else if TicketboxReinstallRequested then
    Result := 'reinstall-{#ReleaseManifestSha256}';
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
  Result := (not TicketboxRestoreRequested) and (not TicketboxUpgradeRequested) and
    (not TicketboxReinstallRequested) and
    (TicketboxExactActiveCanContinue or TicketboxCommittedReplayCanContinue);
end;

function TicketboxFreshMaterialization: Boolean;
begin
  Result := (not TicketboxUpgradeRequested) and (not TicketboxExactResumeMaterialization);
end;

function TicketboxDirectSharedMaterialization: Boolean;
begin
  Result := not TicketboxUpgradeRequested;
end;

function TicketboxUpgradeStageReady: Boolean;
begin
  Result := TicketboxUpgradeRequested and (not TicketboxInstallFailed);
end;

function TicketboxUpgradeStageParent: String;
begin
  Result := ExpandConstant('{autopf}\Ticketbox-UpgradeStage');
end;

function TicketboxUpgradeStageDir: String;
begin
  Result := TicketboxUpgradeStageParent + '\{#ReleaseId}';
end;

function TicketboxUninstallFilesDir: String;
begin
  Result := ExpandConstant('{commoncf64}\Ticketbox\uninstall');
end;

function TicketboxDirectoryIsEmpty(const DirPath: String): Boolean;
var
  FindData, Handle: LongWord;
  EntryName: String;
begin
  Result := False;
  FindData := TicketboxLocalAlloc($0040, 592);
  if FindData = 0 then
    Exit;
  try
    Handle := TicketboxFindFirstFile(DirPath + '\*', FindData);
    if Handle = $FFFFFFFF then
      Exit;
    try
      while True do
      begin
        if not TicketboxReadFindEntryName(FindData, EntryName) then
          Exit;
        if (EntryName <> '.') and (EntryName <> '..') then
          Exit;
        if not TicketboxFindNextFile(Handle, FindData) then
        begin
          Result := DLLGetLastError = 18;
          Exit;
        end;
      end;
    finally
      TicketboxFindClose(Handle);
    end;
  finally
    TicketboxLocalFree(FindData);
  end;
end;

function TicketboxIsKnownStageRootEntry(const EntryName: String): Boolean;
var
  LowerName: String;
begin
  LowerName := LowerCase(EntryName);
  Result := (LowerName = '.') or (LowerName = '..') or
    (LowerName = 'release-manifest.json') or
    (LowerName = 'backend') or (LowerName = 'manager') or
    (LowerName = 'connector') or (LowerName = 'lifecycle') or
    (LowerName = '_staging') or (LowerName = '_sync_tmp');
end;

function TicketboxStageHasOnlyKnownEntries(const StageDir: String): Boolean;
var
  FindData, Handle: LongWord;
  EntryName: String;
begin
  Result := False;
  FindData := TicketboxLocalAlloc($0040, 592);
  if FindData = 0 then
    Exit;
  try
    Handle := TicketboxFindFirstFile(StageDir + '\*', FindData);
    if Handle = $FFFFFFFF then
      Exit;
    try
      while True do
      begin
        if not TicketboxReadFindEntryName(FindData, EntryName) then
          Exit;
        if not TicketboxIsKnownStageRootEntry(EntryName) then
          Exit;
        if not TicketboxFindNextFile(Handle, FindData) then
        begin
          Result := DLLGetLastError = 18;
          Exit;
        end;
      end;
    finally
      TicketboxFindClose(Handle);
    end;
  finally
    TicketboxLocalFree(FindData);
  end;
end;

function TicketboxUpgradeStageReusableOrEmpty(const StageDir: String): Boolean;
var
  ManifestPath, ObservedSha: String;
begin
  Result := False;
  if not TicketboxPathExists(StageDir) then
  begin
    Result := True;
    Exit;
  end;
  ManifestPath := StageDir + '\release-manifest.json';
  if TicketboxPathExists(ManifestPath) then
  begin
    if not TicketboxPathIsNonReparseType(ManifestPath, False) then
      Exit;
    ObservedSha := LowerCase(GetSHA256OfFile(ManifestPath));
    Result := (ObservedSha <> '') and
      (ObservedSha = LowerCase(TicketboxExpectedReleaseManifestSha256)) and
      TicketboxStageHasOnlyKnownEntries(StageDir);
    Exit;
  end;
  Result := TicketboxDirectoryIsEmpty(StageDir);
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

function TicketboxActionRecoveryText: String;
begin
  if TicketboxRestoreRequested then
    Result := '请保留源备份和失败候选。诊断后使用新的干净隔离环境恢复；不要清空数据或删除操作记录。'
  else if TicketboxUpgradeRequested then
    Result := '请关闭安装程序，处理上述问题后使用 /UPGRADE=YES 重新运行同一个安装包。'
  else if TicketboxReinstallRequested then
    Result := '请关闭安装程序，确认保留数据与版本一致后使用 /REINSTALL=YES 重新运行同一个安装包。'
  else
    Result := '请关闭安装程序，处理上述问题后重新运行同一个安装包。';
end;

function TicketboxUpgradePreflight(var Reason: String): Boolean;
var
  BindingPath, InstalledRelease, BindingBody: String;
  BindingText: AnsiString;
  InstalledVer, TargetVer: Int64;
  Cmp: Integer;
begin
  Result := False;
  Reason := '';
  if (not TicketboxPathIsNonReparseType(ExpandConstant('{autopf}'), True)) or
     (not TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageParent)) or
     (not TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageDir)) then
  begin
    Reason := '受管升级暂存目录不是可信管理员保护目录';
    Exit;
  end;
  if not TicketboxUpgradeStageReusableOrEmpty(TicketboxUpgradeStageDir) then
  begin
    Reason := '检测到不匹配或含诊断材料的受管升级暂存目录，已保留原目录并中止升级';
    Exit;
  end;
  if (not TicketboxPathIsNonReparseType(ExpandConstant('{app}'), True)) or
     (not TicketboxPathIsNonReparseType(ExpandConstant('{commonappdata}\Ticketbox'), True)) or
     (not TicketboxPathIsNonReparseType(ExpandConstant('{commonappdata}\Ticketbox\machine'), True)) then
  begin
    Reason := '已安装的小票夹目录不是可信本地目录';
    Exit;
  end;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if not TicketboxPathIsNonReparseType(BindingPath, False) then
  begin
    Reason := '未检测到已安装的小票夹实例，无法执行升级';
    Exit;
  end;
  if not LoadStringFromFile(BindingPath, BindingText) then
  begin
    Reason := '无法读取已安装的小票夹绑定信息，无法执行升级';
    Exit;
  end;
  BindingBody := String(BindingText);
  InstalledRelease := TicketboxJsonString(BindingBody, 'active_release_id');
  if (InstalledRelease = '') or
     (not StrToVersion(InstalledRelease, InstalledVer)) or
     (not StrToVersion('{#ReleaseId}', TargetVer)) then
  begin
    Reason := '无法解析当前版本或目标版本号，拒绝执行升级';
    Exit;
  end;
  Cmp := ComparePackedVersion(TargetVer, InstalledVer);
  if Cmp < 0 then
  begin
    Reason := '受管升级不允许从 ' + InstalledRelease + ' 降级到 {#ReleaseId}';
    Exit;
  end;
  if (Cmp = 0) and
     (not TicketboxExactActiveCanContinue()) and
     (not TicketboxCommittedReplayCanContinue()) then
  begin
    Reason := '当前已是目标版本 {#ReleaseId}，拒绝重复覆盖安装';
    Exit;
  end;
  Result := True;
end;

function TicketboxReinstallPreflight(var Reason: String): Boolean;
var
  BindingPath, BindingBody: String;
  BindingText: AnsiString;
begin
  Result := False;
  Reason := '';
  if (not TicketboxPathIsNonReparseType(ExpandConstant('{commonappdata}\Ticketbox'), True)) or
     (not TicketboxPathIsNonReparseType(ExpandConstant('{commonappdata}\Ticketbox\machine'), True)) or
     (not TicketboxPathIsNonReparseType(ExpandConstant('{commonappdata}\Ticketbox\data\pgdata'), True)) then
  begin
    Reason := '未检测到可信的保留数据目录，拒绝执行保留数据重装';
    Exit;
  end;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if (not TicketboxPathIsNonReparseType(BindingPath, False)) or
     (not LoadStringFromFile(BindingPath, BindingText)) then
  begin
    Reason := '保留数据重装需要可验证的 installation.json，拒绝接管孤儿数据目录';
    Exit;
  end;
  BindingBody := String(BindingText);
  if (TicketboxJsonString(BindingBody, 'active_release_id') <> '{#ReleaseId}') or
     (TicketboxJsonString(BindingBody, 'release_manifest_sha256') <>
       TicketboxExpectedReleaseManifestSha256) then
  begin
    Reason := '保留数据重装要求安装包与现有安装版本及清单摘要完全一致';
    Exit;
  end;
  Result := True;
end;

function TicketboxRestorePreflight(var Reason: String): Boolean;
var
  ModeCount: Integer;
  RestoreMode: String;
begin
  Result := True;
  Reason := '';
  ModeCount := 0;
  if TicketboxRestoreRequested then
    ModeCount := ModeCount + 1;
  if TicketboxUpgradeRequested then
    ModeCount := ModeCount + 1;
  if TicketboxReinstallRequested then
    ModeCount := ModeCount + 1;
  if ModeCount > 1 then
  begin
    Reason := '不能同时请求恢复、升级或保留数据重装';
    Result := False;
    Exit;
  end;
  if TicketboxUpgradeRequested then
  begin
    Result := TicketboxUpgradePreflight(Reason);
    Exit;
  end;
  if TicketboxReinstallRequested then
  begin
    Result := TicketboxReinstallPreflight(Reason);
    Exit;
  end;
  if not TicketboxRestoreRequested then
    Exit;
  RestoreMode := TicketboxRestoreMode;
  if (RestoreMode <> 'same-environment') and (RestoreMode <> 'cross-machine') then
    Reason := '恢复模式仅支持 same-environment 或 cross-machine'
  else if (ExpandConstant('{param:SOURCEISOLATED|}') <> 'YES') or
     (Length(ExpandConstant('{param:RESTORESHA256|}')) <> 64) or
     (not FileExists(ExpandConstant('{param:RESTORECOPY|}'))) then
    Reason := '恢复需要已隔离的原实例、完整冷备和可信 SHA-256'
  else if DirExists(ExpandConstant('{commonappdata}\Ticketbox\data')) or
     FileExists(TicketboxActivePath) or
     FileExists(ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json')) then
    Reason := '受控恢复只接受干净隔离环境；保留已有数据和中断候选';
  Result := Reason = '';
end;

function TicketboxPrepareFailure(const Reason: String): String;
begin
  Log('Ticketbox preflight failed: ' + Reason);
  Result := Reason + '。' + #13#10 +
    TicketboxActionRecoveryText + #13#10 +
    '安装日志：' + ExpandConstant('{log}');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  BindingPath, LeaseFailure, ResultFailure: String;
begin
  { The outer lease is coordination only; product preflight remains read-only. }
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
  if (not TicketboxPathIsNonReparseType(ExpandConstant('{commoncf64}'), True)) or
     (not TicketboxPathAbsentOrAdminWriteOnlyDir(ExpandConstant('{commoncf64}\Ticketbox'))) or
     (not TicketboxPathAbsentOrAdminProtectedDir(TicketboxUninstallFilesDir)) then
  begin
    Result := TicketboxPrepareFailure('卸载元数据目录不是可信管理员保护目录');
    Exit;
  end;
  if not TicketboxAcquireSetupLease(LeaseFailure) then
  begin
    Result := TicketboxPrepareFailure(LeaseFailure);
    Exit;
  end;
  if not TicketboxPreparePrivateResult(ResultFailure) then
  begin
    Result := TicketboxPrepareFailure(ResultFailure);
    Exit;
  end;
  if Length(TicketboxExpectedReleaseManifestSha256) <> 64 then
  begin
    Result := TicketboxPrepareFailure('安装包缺少 immutable release manifest 身份');
    Exit;
  end;
  if not TicketboxRestorePreflight(ResultFailure) then
  begin
    Result := TicketboxPrepareFailure(ResultFailure);
    Exit;
  end;
  if FileExists(TicketboxActivePath) and (not TicketboxExactActiveCanContinue()) then
  begin
    Result := TicketboxPrepareFailure('检测到另一个或损坏的首次安装操作；拒绝接管');
    Exit;
  end;
  BindingPath := ExpandConstant('{commonappdata}\Ticketbox\machine\installation.json');
  if FileExists(BindingPath) and (not TicketboxCommittedReplayCanContinue()) and
     (not TicketboxExactActiveCanContinue()) and (not TicketboxUpgradeRequested) and
     (not TicketboxReinstallRequested) then
  begin
    Result := TicketboxPrepareFailure('这台电脑已经安装小票夹；首次安装不会覆盖现有数据');
    Exit;
  end;
end;

procedure DeinitializeSetup;
begin
  if TicketboxUpgradeStageOwned and
     TicketboxVerifyReadOnlyAdminDirectory(TicketboxUpgradeStageParent) and
     TicketboxVerifyReadOnlyAdminDirectory(TicketboxUpgradeStageDir) then
  begin
    if not TicketboxStageHasOnlyKnownEntries(TicketboxUpgradeStageDir) then
      Log('Ticketbox upgrade stage preserved due to extra entries: ' + TicketboxUpgradeStageDir)
    else if (not DelTree(TicketboxUpgradeStageDir, True, True, True)) or
            TicketboxPathExists(TicketboxUpgradeStageDir) then
      Log('Ticketbox upgrade stage cleanup incomplete: ' + TicketboxUpgradeStageDir)
    else
      RemoveDir(TicketboxUpgradeStageParent);
  end;
  TicketboxReleasePrivateResult;
  TicketboxReleaseSetupLease;
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

function TicketboxUpgradeNeedsVcRedist: Boolean;
var
  Reason: String;
begin
  Result := TicketboxUpgradeStageReady and (not TicketboxMsvcRuntimeIsCurrent(Reason));
end;

function TicketboxResultIsCommitted(const OperationId: String): Boolean;
var
  Text: AnsiString;
  Body, Observed: String;
begin
  Result := False;
  TicketboxPairingCode := '';
  TicketboxPairingExpiresAt := '';
  TicketboxRestoreModeResult := '';
  TicketboxReconnectGuidance := '';
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
  TicketboxRestoreModeResult := TicketboxJsonString(Body, 'restore_mode');
  TicketboxReconnectGuidance := TicketboxJsonString(Body, 'client_reconnect_guidance');
  if TicketboxUpgradeRequested then
    Result := (TicketboxJsonString(Body, 'command') = 'upgrade') and
      (TicketboxPairingCode = '') and (TicketboxPairingExpiresAt = '')
  else if TicketboxReinstallRequested then
    Result := (TicketboxJsonString(Body, 'command') = 'reinstall') and
      (TicketboxPairingCode = '') and (TicketboxPairingExpiresAt = '')
  else
    Result := (TicketboxPairingCode <> '') and (TicketboxPairingExpiresAt <> '');
end;

function TicketboxResultFailure: String;
var
  Text: AnsiString;
  Body, Code, Phase: String;
begin
  Result := '生命周期控制器没有返回可验证结果';
  if not LoadStringFromFile(TicketboxResultPath, Text) then
    Exit;
  Body := String(Text);
  Code := TicketboxJsonString(Body, 'code');
  Phase := TicketboxJsonString(Body, 'phase');
  if (Phase = 'rolled_back_to_previous') and (Code = 'upgrade_failed_restored_previous') then
  begin
    TicketboxUpgradeRolledBack := True;
    TicketboxRestoredReleaseId := TicketboxJsonString(Body, 'restored_release_id');
    TicketboxPairingCode := TicketboxJsonString(Body, 'pairing_code');
    TicketboxPairingExpiresAt := TicketboxJsonString(Body, 'pairing_expires_at');
    Result := '升级未完成，已从升级前冷备安全恢复至旧版本并重新开放服务（错误代码：' + Code + '）';
    Exit;
  end;
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
  if TicketboxRestoreRequested then
    Command := 'restore';
  if TicketboxUpgradeRequested then
    Command := 'upgrade';
  if TicketboxReinstallRequested then
    Command := 'reinstall';
  if TicketboxUpgradeRequested then
  begin
    if (not TicketboxVerifyReadOnlyAdminDirectory(TicketboxUpgradeStageParent)) or
       (not TicketboxVerifyReadOnlyAdminDirectory(TicketboxUpgradeStageDir)) then
    begin
      TicketboxMarkInstallFailed('受管升级暂存目录不是可信管理员保护目录');
      Exit;
    end;
    ManifestPath := TicketboxUpgradeStageDir + '\release-manifest.json';
  end
  else
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
  if TicketboxRestoreRequested then
    Result := Result + ' --source "' + ExpandConstant('{param:RESTORECOPY|}') +
      '" --sha256 "' + LowerCase(ExpandConstant('{param:RESTORESHA256|}')) +
      '" --restore-mode "' + TicketboxRestoreMode + '" --source-isolated';
  if TicketboxUpgradeRequested then
  begin
    Result := Result + ' --staged-release-root "' + TicketboxUpgradeStageDir + '"';
    if not TicketboxUpgradeRollbackDisabled then
      Result := Result + ' --rollback-on-failure';
  end;
end;

function TicketboxIsHexSha256(const Value: String): Boolean;
var
  Lowered: String;
  I: Integer;
  Ch: Char;
begin
  Result := False;
  Lowered := LowerCase(Value);
  if Length(Lowered) <> 64 then
    Exit;
  for I := 1 to 64 do
  begin
    Ch := Lowered[I];
    if not (((Ch >= '0') and (Ch <= '9')) or ((Ch >= 'a') and (Ch <= 'f'))) then
      Exit;
  end;
  Result := True;
end;

function TicketboxUninstallResultIsCommitted: Boolean;
var
  Text: AnsiString;
  Body, ObservedOpId, DigestPart: String;
begin
  Result := False;
  if not LoadStringFromFile(TicketboxResultPath, Text) then
    Exit;
  Body := String(Text);
  ObservedOpId := TicketboxJsonString(Body, 'operation_id');
  if (Length(ObservedOpId) <> 74) or (Copy(ObservedOpId, 1, 10) <> 'uninstall-') then
    Exit;
  DigestPart := Copy(ObservedOpId, 11, 64);
  if (not TicketboxIsHexSha256(DigestPart)) or (DigestPart <> LowerCase(DigestPart)) then
    Exit;
  if TicketboxJsonString(Body, 'command') <> 'uninstall' then
    Exit;
  if TicketboxJsonString(Body, 'code') <> 'uninstalled_data_preserved' then
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
  Result := (Pos('"installation_published": true', Body) > 0) or
    (Pos('"installation_published":true', Body) > 0);
end;

function TicketboxUninstallPreflightOk(
  const LifecycleDir, LifecycleExe: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not TicketboxPathIsNonReparseType(LifecycleExe, False) then
    Exit;
  if not Exec(
    LifecycleExe,
    'uninstall --check-preflight',
    LifecycleDir,
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode) then
    Exit;
  Result := ResultCode = 0;
end;

procedure TicketboxReportUninstallRefused(const Reason: String);
begin
  Log('Ticketbox uninstall refused: ' + Reason);
  SuppressibleMsgBox(
    '小票夹受控卸载未完成：' + Reason + '。' + #13#10 +
    '为保护服务与数据安全，卸载已中止，程序与数据保持原样。',
    mbError, MB_OK, IDOK);
end;

procedure TicketboxAbortUninstall(const Reason: String);
begin
  Log('Ticketbox uninstall aborted: ' + Reason);
  TicketboxReleasePrivateResult;
  TicketboxReleaseSetupLease;
  SuppressibleMsgBox(
    '小票夹受控卸载未完成：' + Reason + '。' + #13#10 +
    '为保护服务与数据安全，卸载已中止，程序与数据保持原样。',
    mbError, MB_OK, IDOK);
end;

function InitializeUninstall: Boolean;
var
  LifecycleDir, LifecycleExe: String;
begin
  { InitializeUninstall runs before the uninstall confirmation dialog; keep it read-only. }
  Result := False;
  TicketboxSetupLeaseHandle := 0;
  TicketboxResultDirectoryHandle := 0;
  LifecycleDir := ExpandConstant('{app}\bin\lifecycle');
  LifecycleExe := LifecycleDir + '\TicketboxLifecycle.exe';
  if not TicketboxPathIsNonReparseType(LifecycleExe, False) then
  begin
    TicketboxReportUninstallRefused('缺少可信的生命周期控制器，无法执行受控卸载');
    Exit;
  end;
  if not TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe) then
  begin
    if TicketboxPathExists(TicketboxActivePath) then
      TicketboxReportUninstallRefused('检测到正在进行的生命周期操作，拒绝卸载')
    else
      TicketboxReportUninstallRefused('受控卸载预检未通过，拒绝卸载');
    Exit;
  end;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  LeaseFailure, ResultFailure: String;
  LifecycleDir, LifecycleExe, Params, FailureCode: String;
  ResultText: AnsiString;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  if not TicketboxAcquireSetupLease(LeaseFailure) then
  begin
    TicketboxAbortUninstall(LeaseFailure);
    Abort;
  end;
  LifecycleDir := ExpandConstant('{app}\bin\lifecycle');
  LifecycleExe := LifecycleDir + '\TicketboxLifecycle.exe';
  if not TicketboxPathIsNonReparseType(LifecycleExe, False) then
  begin
    TicketboxAbortUninstall('缺少可信的生命周期控制器，无法执行受控卸载');
    Abort;
  end;
  if not TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe) then
  begin
    if TicketboxPathExists(TicketboxActivePath) then
      TicketboxAbortUninstall('检测到正在进行的生命周期操作，拒绝卸载')
    else
      TicketboxAbortUninstall('受控卸载预检未通过，拒绝卸载');
    Abort;
  end;
  if not TicketboxPreparePrivateResult(ResultFailure) then
  begin
    TicketboxAbortUninstall(ResultFailure);
    Abort;
  end;
  if FileExists(TicketboxResultPath) and (not DeleteFile(TicketboxResultPath)) then
  begin
    TicketboxAbortUninstall('无法清理上一次受保护结果文件');
    Abort;
  end;
  Params := 'uninstall --from-installed --result "' + TicketboxResultPath + '"';
  if (not Exec(LifecycleExe, Params, LifecycleDir, SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
     (ResultCode <> 0) or
     (not TicketboxUninstallResultIsCommitted) then
  begin
    FailureCode := '';
    if LoadStringFromFile(TicketboxResultPath, ResultText) then
      FailureCode := TicketboxJsonString(String(ResultText), 'code');
    if FailureCode <> '' then
      TicketboxAbortUninstall('生命周期控制器拒绝或未完成卸载（错误代码：' + FailureCode + '）')
    else
      TicketboxAbortUninstall('生命周期控制器未返回已提交的卸载结果（退出码：' + IntToStr(ResultCode) + '）');
    Abort;
  end;
  TicketboxDeletePrivateResult;
end;

procedure DeinitializeUninstall;
begin
  TicketboxReleasePrivateResult;
  TicketboxReleaseSetupLease;
end;

function TicketboxRestoreGuidanceText: String;
begin
  if (TicketboxRestoreModeResult = 'cross_machine') or
     (TicketboxRestoreMode = 'cross-machine') then
    Result :=
      '跨机恢复（R2）后续必做步骤：' + #13#10 +
      '1. 保持旧主机隔离；在重新配置公网连接前，请先吊销或停用旧远端公网隧道。' + #13#10 +
      '2. 请使用新配对码重新配对“管理小票夹”，并将 Android/Web 重新接入新主机代际。' + #13#10 +
      '3. 请在各端显式核对待提交意图（Outbox），切勿清空客户端数据或盲目自动重发未核验请求。'
  else
    Result :=
      '恢复（R1）后续步骤：请使用新配对码重新配对“管理小票夹”，' +
      '重新接入客户端并显式核对待提交意图（Outbox），切勿清空客户端数据。';
  if TicketboxReconnectGuidance <> '' then
    Result := Result + #13#10 + #13#10 + '恢复指引详情：' + TicketboxReconnectGuidance;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Reason, FailureMessage, SuccessMessage: String;
  StageParentHandle, StageDirHandle, UninstallDirHandle: LongWord;
begin
  if CurStep = ssInstall then
  begin
    if (not TicketboxPathIsNonReparseType(ExpandConstant('{commoncf64}'), True)) or
       (not TicketboxPathAbsentOrAdminWriteOnlyDir(ExpandConstant('{commoncf64}\Ticketbox'))) or
       (not TicketboxPathAbsentOrAdminProtectedDir(TicketboxUninstallFilesDir)) then
    begin
      TicketboxMarkInstallFailed('卸载元数据目录不是可信管理员保护目录');
      Abort;
    end;
    UninstallDirHandle := $FFFFFFFF;
    if not TicketboxCreateProtectedDirectory(
      TicketboxUninstallFilesDir,
      'O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)',
      UninstallDirHandle) then
    begin
      TicketboxMarkInstallFailed('无法创建受保护的卸载元数据目录');
      Abort;
    end;
    TicketboxCloseHandle(UninstallDirHandle);
  end;
  if (CurStep = ssInstall) and TicketboxUpgradeRequested then
  begin
    if (not TicketboxPathIsNonReparseType(ExpandConstant('{autopf}'), True)) or
       (not TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageParent)) or
       (not TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageDir)) then
    begin
      TicketboxMarkInstallFailed('受管升级暂存目录不是可信管理员保护目录');
      Abort;
    end;
    if not TicketboxUpgradeStageReusableOrEmpty(TicketboxUpgradeStageDir) then
    begin
      TicketboxMarkInstallFailed('检测到不匹配或含诊断材料的受管升级暂存目录，已保留原目录并中止升级');
      Abort;
    end;
    if TicketboxPathExists(TicketboxUpgradeStageDir) and
       ((not DelTree(TicketboxUpgradeStageDir, True, True, True)) or
        TicketboxPathExists(TicketboxUpgradeStageDir)) then
    begin
      TicketboxMarkInstallFailed('无法清理残留的受管升级暂存目录');
      Abort;
    end;
    StageParentHandle := $FFFFFFFF;
    StageDirHandle := $FFFFFFFF;
    if not TicketboxCreateProtectedDirectory(
      TicketboxUpgradeStageParent,
      'O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)',
      StageParentHandle) then
    begin
      TicketboxMarkInstallFailed('无法创建受保护的受管升级暂存父目录');
      Abort;
    end;
    TicketboxCloseHandle(StageParentHandle);
    if not TicketboxCreateProtectedDirectory(
      TicketboxUpgradeStageDir,
      'O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)',
      StageDirHandle) then
    begin
      TicketboxMarkInstallFailed('无法创建受保护的受管升级暂存目录');
      Abort;
    end;
    TicketboxCloseHandle(StageDirHandle);
    TicketboxUpgradeStageOwned := True;
  end;
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
    begin
      if TicketboxUpgradeRolledBack then
      begin
        FailureMessage := '小票夹升级未完成：' + TicketboxInstallFailureReason + '。';
        if TicketboxRestoredReleaseId <> '' then
          FailureMessage := FailureMessage + #13#10 + '已恢复版本：' + TicketboxRestoredReleaseId;
        if (TicketboxPairingCode <> '') and (TicketboxPairingExpiresAt <> '') then
          FailureMessage := FailureMessage + #13#10 + '恢复后配对码：' + TicketboxPairingCode +
            '（有效期至：' + TicketboxPairingExpiresAt + '）';
        FailureMessage := FailureMessage + #13#10 + '安装日志：' + ExpandConstant('{log}');
      end
      else
        FailureMessage := '小票夹安装未完成：' + TicketboxInstallFailureReason + '。' + #13#10 +
          TicketboxActionRecoveryText + #13#10 +
          '安装日志：' + ExpandConstant('{log}');
      TicketboxDeletePrivateResult;
      SuppressibleMsgBox(FailureMessage, mbError, MB_OK, IDOK);
    end
    else
    begin
      if TicketboxUpgradeRequested then
        SuccessMessage := '小票夹升级完成。现有数据与绑定身份已保留，请打开“管理小票夹”继续使用。'
      else if TicketboxReinstallRequested then
        SuccessMessage := '小票夹保留数据重装完成。现有数据、原件与绑定身份已保留，请打开“管理小票夹”继续使用。'
      else if TicketboxRestoreRequested then
      begin
        if TicketboxReconnectGuidance <> '' then
          Log('Ticketbox recovery guidance (' + TicketboxRestoreModeResult + '): ' +
            TicketboxReconnectGuidance);
        SuccessMessage := '小票夹受控恢复完成。' + #13#10 + #13#10 +
          '恢复后配对码：' + TicketboxPairingCode + #13#10 +
          '有效期至：' + TicketboxPairingExpiresAt + #13#10 + #13#10 +
          TicketboxRestoreGuidanceText;
      end
      else
        SuccessMessage := '小票夹安装完成。' + #13#10 + #13#10 +
          '首次配对码：' + TicketboxPairingCode + #13#10 +
          '有效期至：' + TicketboxPairingExpiresAt + #13#10 + #13#10 +
          '请打开“管理小票夹”完成设备绑定。';
      SuppressibleMsgBox(SuccessMessage, mbInformation, MB_OK, IDOK);
      TicketboxDeletePrivateResult;
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    if TicketboxInstallFailed then
    begin
      if TicketboxUpgradeRolledBack then
      begin
        WizardForm.FinishedHeadingLabel.Caption := '小票夹升级未完成（已安全恢复旧版本）';
        WizardForm.FinishedLabel.Caption := TicketboxInstallFailureReason + '。' + #13#10 +
          '安装日志：' + ExpandConstant('{log}');
      end
      else
      begin
        WizardForm.FinishedHeadingLabel.Caption := '小票夹安装未完成';
        WizardForm.FinishedLabel.Caption := TicketboxInstallFailureReason + '。' + #13#10 +
          TicketboxActionRecoveryText + #13#10 +
          '安装日志：' + ExpandConstant('{log}');
      end;
    end
    else if TicketboxRestoreRequested then
    begin
      WizardForm.FinishedHeadingLabel.Caption := '小票夹受控恢复完成';
      WizardForm.FinishedLabel.Caption := TicketboxRestoreGuidanceText + #13#10 +
        '安装日志：' + ExpandConstant('{log}');
    end;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if TicketboxUpgradeRolledBack then
    Result := 3
  else if TicketboxInstallFailed then
    Result := 1
  else
    Result := 0;
end;
