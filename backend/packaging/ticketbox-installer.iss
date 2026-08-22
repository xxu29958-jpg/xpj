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
#ifndef WindowsSecurityPrimitivesScriptSha256
#error WindowsSecurityPrimitivesScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsSecurityByteArrayScriptSha256
#error WindowsSecurityByteArrayScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsSecurityTokenPrivilegeNativeScriptSha256
#error WindowsSecurityTokenPrivilegeNativeScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsSecurityTokenPrivilegeScriptSha256
#error WindowsSecurityTokenPrivilegeScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsSecurityDescriptorComparisonScriptSha256
#error WindowsSecurityDescriptorComparisonScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsSecurityDescriptorDiagnosticScriptSha256
#error WindowsSecurityDescriptorDiagnosticScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef WindowsSecurityFileSecurityScriptSha256
#error WindowsSecurityFileSecurityScriptSha256 must be injected by build_inno_installer.ps1
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
#ifndef ServiceIdentityScriptSha256
#error ServiceIdentityScriptSha256 must be injected by build_inno_installer.ps1
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
#ifndef DatabaseGenerationScriptSha256
#error DatabaseGenerationScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationContractScriptSha256
#error DatabaseGenerationContractScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationReleaseScriptSha256
#error DatabaseGenerationReleaseScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef OperationFailureScriptSha256
#error OperationFailureScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationArtifactsScriptSha256
#error DatabaseGenerationArtifactsScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationCommitVerifierScriptSha256
#error DatabaseGenerationCommitVerifierScriptSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationProgramSha256
#error DatabaseGenerationProgramSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseMaintenanceHelperSize
#error DatabaseMaintenanceHelperSize must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseMaintenanceHelperSha256
#error DatabaseMaintenanceHelperSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationPgDumpSize
#error DatabaseGenerationPgDumpSize must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationPgDumpSha256
#error DatabaseGenerationPgDumpSha256 must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationPgRestoreSize
#error DatabaseGenerationPgRestoreSize must be injected by build_inno_installer.ps1
#endif
#ifndef DatabaseGenerationPgRestoreSha256
#error DatabaseGenerationPgRestoreSha256 must be injected by build_inno_installer.ps1
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
OutputManifestFile=ticketbox-installer-content.tsv
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
Source: "windows_service_identity.ps1"; Flags: dontcopy noencryption
Source: "windows_service_lifecycle.ps1"; Flags: dontcopy noencryption
Source: "windows_installation_safety.ps1"; Flags: dontcopy noencryption
Source: "windows_security_primitives.ps1"; Flags: dontcopy noencryption
Source: "security_primitives\byte_array.ps1"; DestName: "ticketbox-security-byte-array.ps1"; Flags: dontcopy noencryption
Source: "security_primitives\token_privilege_native.ps1"; DestName: "ticketbox-security-token-privilege-native.ps1"; Flags: dontcopy noencryption
Source: "security_primitives\token_privilege.ps1"; DestName: "ticketbox-security-token-privilege.ps1"; Flags: dontcopy noencryption
Source: "security_primitives\descriptor_comparison.ps1"; DestName: "ticketbox-security-descriptor-comparison.ps1"; Flags: dontcopy noencryption
Source: "security_primitives\descriptor_diagnostic.ps1"; DestName: "ticketbox-security-descriptor-diagnostic.ps1"; Flags: dontcopy noencryption
Source: "security_primitives\file_security.ps1"; DestName: "ticketbox-security-file-security.ps1"; Flags: dontcopy noencryption
Source: "windows_lifecycle_receipt.ps1"; Flags: dontcopy noencryption
Source: "windows_lifecycle_lock.ps1"; Flags: dontcopy noencryption
Source: "hold_installer_lifecycle_lock.ps1"; Flags: dontcopy noencryption
Source: "install_windows_prerequisites.ps1"; Flags: dontcopy noencryption
Source: "vendor\vc-runtime\vc_redist.x64.exe"; DestName: "vc_redist.x64.exe"; Flags: dontcopy noencryption
Source: "windows_database_safety.ps1"; Flags: dontcopy noencryption
Source: "windows_pg_recovery_tools.ps1"; Flags: dontcopy noencryption
Source: "windows_release_config.ps1"; Flags: dontcopy noencryption
Source: "windows-release-config.json"; Flags: dontcopy noencryption
Source: "windows_database_generation.ps1"; Flags: dontcopy noencryption
Source: "windows_database_generation_contract.ps1"; Flags: dontcopy noencryption
Source: "windows_database_generation_release.ps1"; Flags: dontcopy noencryption
Source: "windows_operation_failure.ps1"; Flags: dontcopy noencryption
Source: "windows_database_generation_artifacts.ps1"; Flags: dontcopy noencryption
Source: "windows_database_generation_commit_verifier.ps1"; Flags: dontcopy noencryption
Source: "windows_database_generation_policy.ps1"; Flags: dontcopy noencryption
Source: "..\dist\ticketbox-backend\DATABASE_GENERATION_PROGRAM.json"; DestName: "DATABASE_GENERATION_PROGRAM.json"; Flags: dontcopy noencryption
Source: "ticketbox.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ticketbox-backend\DATABASE_GENERATION_PROGRAM.json"; DestDir: "{app}\program\ticketbox-backend"; Flags: ignoreversion
Source: "..\dist\ticketbox-backend\*"; DestDir: "{app}\program\ticketbox-backend"; Excludes: "ticketbox-data\*,DATABASE_GENERATION_PROGRAM.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\desktop\dist\ticketbox-manager\*"; DestDir: "{app}\manager"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\pg\*"; DestDir: "{app}\pg"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vendor\shawl\shawl.exe"; DestDir: "{app}\shawl"; Flags: ignoreversion
Source: "vendor\shawl\shawl-v1.9.0-legal.txt"; DestDir: "{app}\shawl"; Flags: ignoreversion
Source: "hold_data_root_mutation_guard.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "prepare_bundled_upgrade.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_service_contract.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_service_identity.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_service_lifecycle.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_installation_safety.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_lifecycle_receipt.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_lifecycle_lock.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "hold_installer_lifecycle_lock.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_safety.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_pg_recovery_tools.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_postgresql_database_catalog.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "postgresql_database_catalog\primitives.ps1"; DestDir: "{app}\installer\postgresql_database_catalog"; Flags: ignoreversion
Source: "postgresql_database_catalog\query.ps1"; DestDir: "{app}\installer\postgresql_database_catalog"; Flags: ignoreversion
Source: "postgresql_database_catalog\codec.ps1"; DestDir: "{app}\installer\postgresql_database_catalog"; Flags: ignoreversion
Source: "postgresql_database_catalog\observation.ps1"; DestDir: "{app}\installer\postgresql_database_catalog"; Flags: ignoreversion
Source: "windows_postgresql_writer_fence.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "postgresql_writer_fence\primitives.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\observation_query.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\observation_codec.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\observation.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\reconcile_policy.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\precondition_guard.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\session_drain.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "postgresql_writer_fence\reconciler.ps1"; DestDir: "{app}\installer\postgresql_writer_fence"; Flags: ignoreversion
Source: "windows_release_config.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_bundled_database.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_postgresql_database_command.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_ticketbox_database_contract.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_ticketbox_database_acl.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_ticketbox_database_acl_observation.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_ticketbox_database_roles.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_security_primitives.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "security_primitives\byte_array.ps1"; DestDir: "{app}\installer\security_primitives"; Flags: ignoreversion
Source: "security_primitives\token_privilege_native.ps1"; DestDir: "{app}\installer\security_primitives"; Flags: ignoreversion
Source: "security_primitives\token_privilege.ps1"; DestDir: "{app}\installer\security_primitives"; Flags: ignoreversion
Source: "security_primitives\descriptor_comparison.ps1"; DestDir: "{app}\installer\security_primitives"; Flags: ignoreversion
Source: "security_primitives\descriptor_diagnostic.ps1"; DestDir: "{app}\installer\security_primitives"; Flags: ignoreversion
Source: "security_primitives\file_security.ps1"; DestDir: "{app}\installer\security_primitives"; Flags: ignoreversion
Source: "windows_postgresql_credentials.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_postgresql_single_user.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_deadline_budget.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_atomic_artifacts.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "atomic_artifacts\native.ps1"; DestDir: "{app}\installer\atomic_artifacts"; Flags: ignoreversion
Source: "atomic_artifacts\file.ps1"; DestDir: "{app}\installer\atomic_artifacts"; Flags: ignoreversion
Source: "atomic_artifacts\directory.ps1"; DestDir: "{app}\installer\atomic_artifacts"; Flags: ignoreversion
Source: "windows_database_generation_program_adapter.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_program_execution.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_contract.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_release.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_operation_failure.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_artifacts.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_commit_verifier.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_policy.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_credentials.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_role_fence.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_database_binding.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_host_authority.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_role_bootstrap.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_source.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_source_binding.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_current.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_recovery_evidence.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_target_recovery.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_target_authorization.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_retirement.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_single_user.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_database_generation_projection.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_dataset_backup.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_dataset_restore.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_installed_dataset_reader.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_installed_dataset_operation.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_installed_dataset_restore_artifacts.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_installed_dataset_restore_verification.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_dataset_restore_filesystem.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_dataset_restore_reducer.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_dataset_restore_database.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_dataset_restore_runtime.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_postgresql_candidate_cluster.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_postgresql_candidate_initdb.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_postgresql_candidate_runtime.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "windows_backend_health.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
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
Name: "{autoprograms}\小票夹\小票夹连接与恢复"; Filename: "http://127.0.0.1:{code:GetBackendPort}/owner"; IconFilename: "{app}\ticketbox.ico"
Name: "{autoprograms}\小票夹\数据目录"; Filename: "{code:GetDataRoot}"; IconFilename: "{app}\ticketbox.ico"

[Code]
#include "ticketbox-installer-windows.isph"
#include "ticketbox-installer-flow.isph"
