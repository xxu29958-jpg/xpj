#ifndef AppVersion
#error AppVersion must be injected by build_inno_installer.ps1
#endif
#ifndef AppVersionInfo
#error AppVersionInfo must be derived and injected by build_inno_installer.ps1
#endif
#ifndef PgServiceName
#error PgServiceName must be injected from windows-release-config.json
#endif
#ifndef BackendServiceName
#error BackendServiceName must be injected from windows-release-config.json
#endif
#ifndef DefaultPgPort
#error DefaultPgPort must be injected from windows-release-config.json
#endif
#ifndef FallbackPgPort
#error FallbackPgPort must be injected from windows-release-config.json
#endif
#ifndef DefaultBackendPort
#error DefaultBackendPort must be injected from windows-release-config.json
#endif
#ifndef FallbackBackendPort
#error FallbackBackendPort must be injected from windows-release-config.json
#endif
#ifndef TargetPgMajor
#error TargetPgMajor must be probed from vendor PostgreSQL by build_inno_installer.ps1
#endif
#ifndef LifecycleSafetyScriptSha256
#error LifecycleSafetyScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef LifecycleLockScriptSha256
#error LifecycleLockScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef LifecycleHolderScriptSha256
#error LifecycleHolderScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DataRootGuardScriptSha256
#error DataRootGuardScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef PrepareScriptSha256
#error PrepareScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef ServiceContractScriptSha256
#error ServiceContractScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef ServiceLifecycleScriptSha256
#error ServiceLifecycleScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef LifecycleReceiptScriptSha256
#error LifecycleReceiptScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseSafetyScriptSha256
#error DatabaseSafetyScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef PgRecoveryToolsScriptSha256
#error PgRecoveryToolsScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef ReleaseConfigScriptSha256
#error ReleaseConfigScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef ReleaseConfigJsonSha256
#error ReleaseConfigJsonSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef BuildProvenanceScriptSha256
#error BuildProvenanceScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef BackendBuildProvenanceScriptSha256
#error BackendBuildProvenanceScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsPrerequisiteScriptSha256
#error WindowsPrerequisiteScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef VisualCppRuntimeVersion
#error VisualCppRuntimeVersion must be injected by build_inno_installer.ps1
#endif
#ifndef VisualCppRuntimeSha256
#error VisualCppRuntimeSha256 must be injected by build_inno_installer.ps1
#endif
#define AppName "小票夹后端服务"
#define AppPublisher "小票夹"
#define TicketboxAppIdGuid "C97812CE-7486-41D0-AB68-7558A916F6E3"
#define TicketboxAppId "{{" + TicketboxAppIdGuid + "}"

[Setup]
AppId={#TicketboxAppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Ticketbox
DefaultGroupName=小票夹
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableWelcomePage=no
UsePreviousAppDir=no
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
AllowCancelDuringInstall=no
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "chinesesimp"; MessagesFile: "languages\ChineseSimplified.isl"

[InstallDelete]
Type: filesandordirs; Name: "{app}\program\ticketbox-backend\*"; Check: AuthoritativePayloadReplacementPrepared
Type: filesandordirs; Name: "{app}\manager\*"; Check: AuthoritativePayloadReplacementPrepared
Type: filesandordirs; Name: "{app}\pg\*"; Check: AuthoritativePayloadReplacementPrepared
Type: filesandordirs; Name: "{app}\shawl\*"; Check: AuthoritativePayloadReplacementPrepared
Type: filesandordirs; Name: "{app}\installer\*"; Check: AuthoritativePayloadReplacementPrepared

[Files]
Source: "..\scripts\windows_build_provenance.ps1"; DestName: "windows_build_provenance.ps1"; Flags: dontcopy noencryption
Source: "..\scripts\windows_backend_build_provenance.ps1"; DestName: "windows_backend_build_provenance.ps1"; Flags: dontcopy noencryption
Source: "hold_data_root_mutation_guard.ps1"; Flags: dontcopy noencryption
Source: "prepare_bundled_upgrade.ps1"; Flags: dontcopy noencryption
Source: "windows_service_contract.ps1"; Flags: dontcopy noencryption
Source: "windows_service_lifecycle.ps1"; Flags: dontcopy noencryption
Source: "windows_installation_safety.ps1"; Flags: dontcopy noencryption
Source: "windows_lifecycle_receipt.ps1"; Flags: dontcopy noencryption
Source: "windows_lifecycle_lock.ps1"; Flags: dontcopy noencryption
Source: "hold_installer_lifecycle_lock.ps1"; Flags: dontcopy noencryption
Source: "install_windows_prerequisites.ps1"; Flags: dontcopy noencryption
Source: "vendor\vc-runtime\vc_redist.x64.exe"; DestName: "vc_redist.x64.exe"; Flags: dontcopy noencryption
Source: "windows_database_safety.ps1"; Flags: dontcopy noencryption
Source: "windows_pg_recovery_tools.ps1"; Flags: dontcopy noencryption
Source: "windows_release_config.ps1"; Flags: dontcopy noencryption
Source: "windows-release-config.json"; Flags: dontcopy noencryption
Source: "ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ticketbox-backend\*"; DestDir: "{app}\program\ticketbox-backend"; Excludes: "ticketbox-data\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\pg\*"; DestDir: "{app}\pg"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\shawl\shawl.exe"; DestDir: "{app}\shawl"; Flags: ignoreversion
Source: "hold_data_root_mutation_guard.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "prepare_bundled_upgrade.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_service_contract.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_service_lifecycle.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_installation_safety.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_lifecycle_receipt.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_lifecycle_lock.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "hold_installer_lifecycle_lock.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_safety.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_pg_recovery_tools.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_release_config.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_bundled_database.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_database.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_superuser_recovery.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_heartbeat_authority.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_lifecycle.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_heartbeat_helper.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_failure_summary.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_recovery_generation.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_c07_packaged_migration.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_backend_bootstrap.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_bootstrap_exposure_recovery.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows-release-config.json"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\scripts\windows_build_provenance.ps1"; DestDir: "{app}\installer"; DestName: "windows_build_provenance.ps1"; Flags: ignoreversion
Source: "..\scripts\windows_backend_build_provenance.ps1"; DestDir: "{app}\installer"; DestName: "windows_backend_build_provenance.ps1"; Flags: ignoreversion
Source: "..\dist\installer-input\BUILD_PROVENANCE.json"; DestDir: "{app}\installer"; DestName: "BUILD_PROVENANCE.json"; Flags: ignoreversion
Source: "install_bundled_services.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "uninstall_bundled_services.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "DataRoot"; ValueData: "{code:GetDataRoot}"
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "BackendPort"; ValueData: "{code:GetBackendPort}"
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "PgPort"; ValueData: "{code:GetPgPort}"
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "BackendServiceName"; ValueData: "{#BackendServiceName}"
Root: HKLM; Subkey: "Software\Ticketbox"; ValueType: string; ValueName: "PgServiceName"; ValueData: "{#PgServiceName}"

[Icons]
Name: "{autoprograms}\小票夹\管理小票夹"; Filename: "{app}\manager\ticketbox-manager.exe"; WorkingDir: "{app}\manager"; IconFilename: "{app}\ticketbox.ico"
Name: "{autoprograms}\小票夹\打开小票夹 Web"; Filename: "http://127.0.0.1:{code:GetBackendPort}/web"; IconFilename: "{app}\ticketbox.ico"
Name: "{autoprograms}\小票夹\数据目录"; Filename: "{code:GetDataRoot}"; IconFilename: "{app}\ticketbox.ico"

[Code]
#include "ticketbox-installer-windows.isph"
#include "ticketbox-installer-flow.isph"
