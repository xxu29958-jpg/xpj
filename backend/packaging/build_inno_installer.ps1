#Requires -Version 5.1
<#
.SYNOPSIS
  Build the Ticketbox Inno Setup installer.

.DESCRIPTION
  Validates the frozen backend, bundled PostgreSQL, Shawl, and installer scripts,
  then invokes ISCC.exe. Use -CheckInputsOnly on machines without Inno Setup.
  -VerifyOnly requires the installer SHA-256 captured by the compile step so a
  coordinated rewrite of the publish directory cannot self-authorize.
#>
[CmdletBinding()]
param(
    [string]$InnoCompiler = "",
    [string]$VersionContractProbe = "",
    [string]$VersionFloorContractProbe = "",
    [string]$VersionPolicyContractProbe = "",
    [string]$ReleaseConfigOverride = "",
    [switch]$CheckSourceInputsOnly,
    [switch]$CheckInputsOnly,
    [switch]$VerifyOnly,
    [string]$ExpectedInstallerSha256 = "",
    [string]$VerifyPublishDirectory = "",
    [string]$InstallerHashOutputFile = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $BackendRoot "..")).Path
$IssPath = Join-Path $ScriptDir "ticketbox-installer.iss"
$IssWindowsCode = Join-Path $ScriptDir "ticketbox-installer-windows.isph"
$IssFlowCode = Join-Path $ScriptDir "ticketbox-installer-flow.isph"
$ChineseLanguageFile = Join-Path $ScriptDir "languages\ChineseSimplified.isl"
$BackendDist = Join-Path $BackendRoot "dist\ticketbox-backend"
$BackendBuildManifest = Join-Path $BackendDist "BUILD_PROVENANCE.json"
$BuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_build_provenance.ps1"
$BackendBuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_backend_build_provenance.ps1"
$ManagerDist = Join-Path $RepoRoot "desktop\dist\ticketbox-manager"
$ManagerBuildManifest = Join-Path $ManagerDist "BUILD_PROVENANCE.json"
$ManagerBuildProvenanceScript = Join-Path $RepoRoot "desktop\scripts\windows_manager_build_provenance.ps1"
$PgBundle = Join-Path $ScriptDir "vendor\pg"
$PgManifest = Join-Path $PgBundle "BUNDLE_MANIFEST.txt"
$ShawlExe = Join-Path $ScriptDir "vendor\shawl\shawl.exe"
$ShawlLegalNotice = ""
$VisualCppRuntimeExe = Join-Path $ScriptDir "vendor\vc-runtime\vc_redist.x64.exe"
$InstallerInputDir = Join-Path $BackendRoot "dist\installer-input"
$InstallerBuildManifest = Join-Path $InstallerInputDir "BUILD_PROVENANCE.json"
$ToolchainConfigPath = Join-Path $ScriptDir "windows-build-toolchain.json"
$BuildToolchainPrepScript = Join-Path $ScriptDir "prepare_windows_build_toolchain.ps1"
$ReleaseConfigPath = Join-Path $ScriptDir "windows-release-config.json"
if ($ReleaseConfigOverride.Trim().Length -gt 0) {
    $ReleaseConfigPath = $ReleaseConfigOverride
}
$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"
$PrepareScript = Join-Path $ScriptDir "prepare_bundled_upgrade.ps1"
$ServiceContractScript = Join-Path $ScriptDir "windows_service_contract.ps1"
$ServiceIdentityScript = Join-Path $ScriptDir "windows_service_identity.ps1"
$LifecycleScript = Join-Path $ScriptDir "windows_service_lifecycle.ps1"
$SafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"
$ReceiptScript = Join-Path $ScriptDir "windows_lifecycle_receipt.ps1"
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
$LockHolderScript = Join-Path $ScriptDir "hold_installer_lifecycle_lock.ps1"
$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"
$PgRecoveryToolsScript = Join-Path $ScriptDir "windows_pg_recovery_tools.ps1"
$PostgresqlDatabaseCatalogScript = Join-Path `
    $ScriptDir `
    "windows_postgresql_database_catalog.ps1"
$PostgresqlDatabaseCatalogComponentDir = Join-Path `
    $ScriptDir `
    "postgresql_database_catalog"
$PostgresqlDatabaseCatalogPrimitivesScript = Join-Path `
    $PostgresqlDatabaseCatalogComponentDir `
    "primitives.ps1"
$PostgresqlDatabaseCatalogQueryScript = Join-Path `
    $PostgresqlDatabaseCatalogComponentDir `
    "query.ps1"
$PostgresqlDatabaseCatalogCodecScript = Join-Path `
    $PostgresqlDatabaseCatalogComponentDir `
    "codec.ps1"
$PostgresqlDatabaseCatalogObservationScript = Join-Path `
    $PostgresqlDatabaseCatalogComponentDir `
    "observation.ps1"
$PostgresqlWriterFenceScript = Join-Path `
    $ScriptDir `
    "windows_postgresql_writer_fence.ps1"
$PostgresqlWriterFenceComponentDir = Join-Path `
    $ScriptDir `
    "postgresql_writer_fence"
$PostgresqlWriterFencePrimitivesScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "primitives.ps1"
$PostgresqlWriterFenceObservationQueryScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "observation_query.ps1"
$PostgresqlWriterFenceObservationCodecScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "observation_codec.ps1"
$PostgresqlWriterFenceObservationScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "observation.ps1"
$PostgresqlWriterFenceReconcilePolicyScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "reconcile_policy.ps1"
$PostgresqlWriterFencePreconditionGuardScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "precondition_guard.ps1"
$PostgresqlWriterFenceSessionDrainScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "session_drain.ps1"
$PostgresqlWriterFenceReconcilerScript = Join-Path `
    $PostgresqlWriterFenceComponentDir `
    "reconciler.ps1"
$DatabaseScript = Join-Path $ScriptDir "windows_bundled_database.ps1"
$PostgresqlDatabaseCommandScript = Join-Path `
    $ScriptDir `
    "windows_postgresql_database_command.ps1"
$TicketboxDatabaseContractScript = Join-Path `
    $ScriptDir `
    "windows_ticketbox_database_contract.ps1"
$TicketboxDatabaseAclScript = Join-Path `
    $ScriptDir `
    "windows_ticketbox_database_acl.ps1"
$TicketboxDatabaseRolesScript = Join-Path `
    $ScriptDir `
    "windows_ticketbox_database_roles.ps1"
$WindowsSecurityPrimitivesScript = Join-Path `
    $ScriptDir `
    "windows_security_primitives.ps1"
$WindowsSecurityPrimitivesComponentDir = Join-Path `
    $ScriptDir `
    "security_primitives"
$WindowsSecurityByteArrayScript = Join-Path `
    $WindowsSecurityPrimitivesComponentDir `
    "byte_array.ps1"
$WindowsSecurityTokenPrivilegeNativeScript = Join-Path `
    $WindowsSecurityPrimitivesComponentDir `
    "token_privilege_native.ps1"
$WindowsSecurityTokenPrivilegeScript = Join-Path `
    $WindowsSecurityPrimitivesComponentDir `
    "token_privilege.ps1"
$WindowsSecurityDescriptorComparisonScript = Join-Path `
    $WindowsSecurityPrimitivesComponentDir `
    "descriptor_comparison.ps1"
$WindowsSecurityDescriptorDiagnosticScript = Join-Path `
    $WindowsSecurityPrimitivesComponentDir `
    "descriptor_diagnostic.ps1"
$WindowsSecurityFileSecurityScript = Join-Path `
    $WindowsSecurityPrimitivesComponentDir `
    "file_security.ps1"
$PostgresqlCredentialsScript = Join-Path `
    $ScriptDir `
    "windows_postgresql_credentials.ps1"
$PostgresqlSingleUserScript = Join-Path `
    $ScriptDir `
    "windows_postgresql_single_user.ps1"
$WindowsDeadlineBudgetScript = Join-Path $ScriptDir "windows_deadline_budget.ps1"
$AtomicArtifactsScript = Join-Path $ScriptDir "windows_atomic_artifacts.ps1"
$AtomicArtifactsComponentDir = Join-Path $ScriptDir "atomic_artifacts"
$AtomicArtifactsNativeScript = Join-Path $AtomicArtifactsComponentDir "native.ps1"
$AtomicArtifactsFileScript = Join-Path $AtomicArtifactsComponentDir "file.ps1"
$AtomicArtifactsDirectoryScript = Join-Path `
    $AtomicArtifactsComponentDir `
    "directory.ps1"
$DatabaseGenerationProgramAdapterScript = Join-Path $ScriptDir "windows_database_generation_program_adapter.ps1"
$DatabaseGenerationProgramExecutionScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_program_execution.ps1"
$DatabaseGenerationScript = Join-Path $ScriptDir "windows_database_generation.ps1"
$DatabaseGenerationContractScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_contract.ps1"
$DatabaseGenerationArtifactsScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_artifacts.ps1"
$DatabaseGenerationCommitVerifierScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_commit_verifier.ps1"
$DatabaseGenerationPolicyScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_policy.ps1"
$DatabaseGenerationCredentialsScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_credentials.ps1"
$DatabaseGenerationRoleFenceScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_role_fence.ps1"
$DatabaseGenerationDatabaseBindingScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_database_binding.ps1"
$DatabaseGenerationSourceScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_source.ps1"
$DatabaseGenerationRecoveryEvidenceScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_recovery_evidence.ps1"
$DatabaseGenerationTargetRecoveryScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_target_recovery.ps1"
$DatabaseGenerationRetirementScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_retirement.ps1"
$DatabaseGenerationSingleUserScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_single_user.ps1"
$DatabaseGenerationProjectionScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_projection.ps1"
$BackendBootstrapScript = Join-Path $ScriptDir "windows_backend_bootstrap.ps1"
$BootstrapExposureRecoveryScript = Join-Path $ScriptDir "windows_bootstrap_exposure_recovery.ps1"
$InstallScript = Join-Path $ScriptDir "install_bundled_services.ps1"
$UninstallScript = Join-Path $ScriptDir "uninstall_bundled_services.ps1"
$DataRootGuardScript = Join-Path $ScriptDir "hold_data_root_mutation_guard.ps1"
$WindowsPrerequisiteScript = Join-Path $ScriptDir "install_windows_prerequisites.ps1"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 $Label：$Path"
    }
}

function Assert-Dir([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "缺少 $Label：$Path"
    }
}

function Find-Iscc {
    if ($InnoCompiler.Trim().Length -gt 0) {
        if (-not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
            throw "指定的 ISCC.exe 不存在：$InnoCompiler"
        }
        return (Resolve-Path -LiteralPath $InnoCompiler).Path
    }
    return $null
}
function Resolve-Version {
    $versionFile = Join-Path $BackendRoot "app\version.py"
    $content = Get-Content -LiteralPath $versionFile -Encoding UTF8 -Raw
    $m = [regex]::Match($content, '(?m)^\s*BACKEND_VERSION\s*=\s*"([^"]+)"\s*$')
    if (-not $m.Success) {
        throw "无法从 app\version.py 读取 BACKEND_VERSION。"
    }
    return $m.Groups[1].Value
}
function Read-TicketboxInstallerVendorContracts([string]$Path) {
    Assert-File $Path "Windows 构建工具链合同"
    try {
        $config = Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
        $postgres = $config.installer_vendor_sources.postgresql
        $shawl = $config.installer_vendor_sources.shawl
        $visualCppRuntime = $config.installer_vendor_sources.visual_cpp_runtime
    }
    catch {
        throw "Windows 构建工具链合同缺少 installer vendor 来源：$Path"
    }
    if (
        [int]$config.schema_version -ne 1 -or
        [string]$postgres.version -notmatch '^\d+\.\d+-\d+$' -or
        [string]$postgres.archive_name -notmatch '^[A-Za-z0-9._-]+\.zip$' -or
        [string]$postgres.url -notmatch '^https://' -or
        [string]$postgres.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [int64]$postgres.payload_file_count -le 0 -or
        [string]$postgres.payload_fingerprint -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]$shawl.version -notmatch '^\d+\.\d+(?:\.\d+)?$' -or
        [string]$shawl.archive_name -notmatch '^[A-Za-z0-9._-]+\.zip$' -or
        [string]$shawl.url -notmatch '^https://' -or
        [string]$shawl.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]$shawl.executable_sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]$shawl.legal.archive_name -cne "shawl-v$($shawl.version)-legal.zip" -or
        [string]$shawl.legal.url -cne (
            "https://github.com/mtkennerly/shawl/releases/download/v{0}/{1}" -f `
                $shawl.version, $shawl.legal.archive_name
        ) -or
        [string]$shawl.legal.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]$shawl.legal.notice_name -cne "shawl-v$($shawl.version)-legal.txt" -or
        [string]$shawl.legal.notice_sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]$visualCppRuntime.version -notmatch '^\d+(?:\.\d+){3}$' -or
        [string]$visualCppRuntime.archive_name -cne 'vc_redist.x64.exe' -or
        [string]$visualCppRuntime.url -notmatch '^https://download\.visualstudio\.microsoft\.com/' -or
        [string]$visualCppRuntime.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        [string]$visualCppRuntime.architecture -cne 'x64' -or
        [string]$visualCppRuntime.file_version -cne [string]$visualCppRuntime.version -or
        [string]$visualCppRuntime.product_version -cne [string]$visualCppRuntime.version -or
        [string]$visualCppRuntime.original_filename -cne 'VC_redist.x64.exe' -or
        [string]$visualCppRuntime.company_name -cne 'Microsoft Corporation' -or
        [string]$visualCppRuntime.signer_subject -notmatch '^CN=Microsoft Corporation,' -or
        [string]$visualCppRuntime.signer_thumbprint -notmatch '^[0-9A-Fa-f]{40}$' -or
        [string]$visualCppRuntime.runtime_file -cne 'VCRUNTIME140.dll'
    ) {
        throw "Windows 构建工具链合同中的 installer vendor 来源无效。"
    }
    return [pscustomobject]@{
        postgresql = $postgres
        shawl = $shawl
        visual_cpp_runtime = $visualCppRuntime
    }
}
function Get-ValidatedPostgresProvenance([string]$BundlePath = $PgBundle) {
    $bundleManifestPath = Join-Path $BundlePath "BUNDLE_MANIFEST.txt"
    foreach ($directory in @("bin", "lib", "share")) {
        Assert-Dir (Join-Path $BundlePath $directory) "PostgreSQL $directory 目录"
    }
    Assert-File (Join-Path $BundlePath "server_license.txt") "PostgreSQL license"
    $criticalNames = @(
        "initdb.exe",
        "postgres.exe",
        "pg_ctl.exe",
        "psql.exe",
        "pg_dump.exe",
        "pg_restore.exe",
        "pg_isready.exe"
    )
    foreach ($name in $criticalNames) {
        Assert-File (Join-Path $BundlePath "bin\$name") "PG $name"
    }

    $manifest = Read-TicketboxPgBundleManifest $bundleManifestPath
    if (
        $manifest["pg_version"] -cne [string]$installerVendorContracts.postgresql.version -or
        $manifest["source_zip"] -cne [string]$installerVendorContracts.postgresql.archive_name -or
        $manifest["source_sha256"].ToLowerInvariant() -cne
            ([string]$installerVendorContracts.postgresql.sha256).ToLowerInvariant() -or
        $manifest["source_url"] -cne [string]$installerVendorContracts.postgresql.url -or
        [int64]$manifest["payload_file_count"] -ne
            [int64]$installerVendorContracts.postgresql.payload_file_count -or
        $manifest["payload_fingerprint"].ToLowerInvariant() -cne
            ([string]$installerVendorContracts.postgresql.payload_fingerprint).ToLowerInvariant()
    ) {
        throw "PostgreSQL bundle manifest 与 Windows 工具链 archive/payload pin 不一致。"
    }
    $postgresExe = Join-Path $BundlePath "bin\postgres.exe"
    $versionOutput = Invoke-TicketboxExecutableProbe $postgresExe @("--version") "PostgreSQL --version"
    $versionMatch = [regex]::Match($versionOutput, '(?m)^postgres \(PostgreSQL\) (\d+)\.(\d+)(?:\.\d+)?\s*$')
    if (-not $versionMatch.Success) {
        throw "无法解析捆绑 PostgreSQL 版本输出：$versionOutput"
    }
    $version = $versionMatch.Groups[0].Value -replace '^postgres \(PostgreSQL\)\s+', ''
    $major = [int]$versionMatch.Groups[1].Value
    $versionPolicy = Assert-TicketboxVendorVersionAllowed $releaseConfig "postgres" $version
    if ($manifest["pg_version"] -notmatch ('^' + [regex]::Escape($version) + '(?:-|$)')) {
        throw "PostgreSQL manifest 与可执行文件版本不一致：manifest=$($manifest['pg_version'])，exe=$version"
    }
    $criticalEvidence = @(
        $criticalNames | ForEach-Object {
            Get-TicketboxFileEvidence $BundlePath (Join-Path $BundlePath "bin\$_")
        }
    )
    $bundlePaths = @(
        Get-ChildItem -LiteralPath $BundlePath -Recurse -File |
            ForEach-Object { $_.FullName }
    )
    $archivePayloadPaths = @(
        Get-ChildItem -LiteralPath $BundlePath -Recurse -File |
            Where-Object { $_.Name -cne "BUNDLE_MANIFEST.txt" } |
            ForEach-Object { $_.FullName }
    )
    $archivePayloadSnapshot = Get-TicketboxFileSetSnapshot $BundlePath $archivePayloadPaths
    if (
        @($archivePayloadSnapshot.files).Count -ne
            [int64]$installerVendorContracts.postgresql.payload_file_count -or
        $archivePayloadSnapshot.fingerprint -cne
            ([string]$installerVendorContracts.postgresql.payload_fingerprint).ToLowerInvariant()
    ) {
        throw "PostgreSQL 实际裁剪 payload 与固定 archive 的确定性产物合同不一致。"
    }
    $bundleSnapshot = Get-TicketboxFileSetSnapshot $BundlePath $bundlePaths
    return [pscustomobject]@{
        major = $major
        version = $version
        version_policy = $versionPolicy
        version_output = $versionOutput
        manifest = $manifest
        archive_payload_snapshot = $archivePayloadSnapshot
        bundle_snapshot = $bundleSnapshot
        critical_files = @($criticalEvidence)
    }
}

function Get-ValidatedShawlProvenance(
    [string]$ExecutablePath = $ShawlExe,
    [string]$LegalNoticePath = $ShawlLegalNotice
) {
    Assert-File $ExecutablePath "shawl.exe"
    Assert-File $LegalNoticePath "Shawl legal notice"
    $versionOutput = Invoke-TicketboxExecutableProbe $ExecutablePath @("--version") "Shawl --version"
    $versionMatch = [regex]::Match($versionOutput, '(?m)^shawl\s+([0-9]+(?:\.[0-9]+){1,3}(?:[-+][0-9A-Za-z.-]+)?)\s*$')
    if (-not $versionMatch.Success) {
        throw "无法解析 Shawl 版本输出：$versionOutput"
    }
    $version = $versionMatch.Groups[1].Value
    if ($version -cne [string]$installerVendorContracts.shawl.version) {
        throw "Shawl 可执行版本与 Windows 工具链合同不一致。"
    }
    $versionPolicy = Assert-TicketboxVendorVersionAllowed $releaseConfig "shawl" $version
    $helpOutput = Invoke-TicketboxExecutableProbe $ExecutablePath @("--help") "Shawl --help"
    foreach ($requiredText in @("Wrap arbitrary commands as Windows services", "add", "run")) {
        if (-not $helpOutput.Contains($requiredText)) {
            throw "Shawl 可执行探针缺少预期能力标记：$requiredText"
        }
    }
    $executableEvidence = Get-TicketboxFileEvidence `
        (Split-Path -Parent $ExecutablePath) `
        $ExecutablePath
    if (
        $executableEvidence.sha256 -cne
            ([string]$installerVendorContracts.shawl.executable_sha256).ToLowerInvariant()
    ) {
        throw "Shawl 可执行 hash 与固定 archive 的 payload pin 不一致。"
    }
    $legalNoticeEvidence = Get-TicketboxFileEvidence `
        (Split-Path -Parent $LegalNoticePath) `
        $LegalNoticePath
    if (
        [IO.Path]::GetFileName($LegalNoticePath) -cne
            [string]$installerVendorContracts.shawl.legal.notice_name -or
        $legalNoticeEvidence.sha256 -cne
            ([string]$installerVendorContracts.shawl.legal.notice_sha256).ToLowerInvariant()
    ) {
        throw "Shawl legal notice 与固定 legal archive 的 payload pin 不一致。"
    }
    return [pscustomobject]@{
        version = $version
        version_policy = $versionPolicy
        version_output = $versionOutput
        executable = $executableEvidence
        legal_archive = [ordered]@{
            name = [string]$installerVendorContracts.shawl.legal.archive_name
            url = [string]$installerVendorContracts.shawl.legal.url
            sha256 = ([string]$installerVendorContracts.shawl.legal.sha256).ToLowerInvariant()
        }
        legal_notice = $legalNoticeEvidence
        probes = @("--version", "--help")
    }
}

function Get-ValidatedVisualCppRuntimeProvenance(
    [string]$ExecutablePath = $VisualCppRuntimeExe
) {
    Assert-File $ExecutablePath "Microsoft Visual C++ x64 Redistributable"
    $source = $installerVendorContracts.visual_cpp_runtime
    $item = Get-Item -LiteralPath $ExecutablePath -Force -ErrorAction Stop
    $versionInfo = $item.VersionInfo
    if (
        [string]$versionInfo.FileVersion -cne [string]$source.file_version -or
        [string]$versionInfo.ProductVersion -cne [string]$source.product_version -or
        [string]$versionInfo.OriginalFilename -cne [string]$source.original_filename -or
        [string]$versionInfo.CompanyName -cne [string]$source.company_name
    ) {
        throw "Microsoft Visual C++ Redistributable 版本资源与工具链合同不一致。"
    }
    $executable = Get-TicketboxFileEvidence `
        (Split-Path -Parent $ExecutablePath) `
        $ExecutablePath
    if ($executable.sha256 -cne ([string]$source.sha256).ToLowerInvariant()) {
        throw "Microsoft Visual C++ Redistributable hash 与固定官方 payload pin 不一致。"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $ExecutablePath
    if (
        $signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        $null -eq $signature.SignerCertificate -or
        [string]$signature.SignerCertificate.Subject -cne [string]$source.signer_subject -or
        [string]$signature.SignerCertificate.Thumbprint -ine [string]$source.signer_thumbprint
    ) {
        throw "Microsoft Visual C++ Redistributable Authenticode 身份与工具链合同不一致。"
    }
    return [pscustomobject]@{
        version = [string]$source.version
        architecture = [string]$source.architecture
        runtime_file = [string]$source.runtime_file
        source_archive = [string]$source.archive_name
        source_url = [string]$source.url
        executable = $executable
        file_version = [string]$versionInfo.FileVersion
        product_version = [string]$versionInfo.ProductVersion
        original_filename = [string]$versionInfo.OriginalFilename
        company_name = [string]$versionInfo.CompanyName
        authenticode = [ordered]@{
            status = [string]$signature.Status
            signer_subject = [string]$signature.SignerCertificate.Subject
            signer_thumbprint = [string]$signature.SignerCertificate.Thumbprint
        }
    }
}

function Get-InstallerBuildInputEvidence(
    [object]$BackendManifest,
    [object]$ManagerManifest,
    [object]$PostgresProvenance,
    [object]$ShawlProvenance,
    [object]$VisualCppRuntimeProvenance
) {
    return [ordered]@{
        backend = [ordered]@{
            version = $BackendManifest.backend_version
            source_algorithm = $BackendManifest.source.algorithm
            source_fingerprint = $BackendManifest.source.fingerprint
            payload_algorithm = $BackendManifest.payload.algorithm
            payload_fingerprint = $BackendManifest.payload.fingerprint
            executable = $BackendManifest.payload.executable
            database_generation_program =
                $BackendManifest.payload.database_generation_program
            database_maintenance_helper =
                $BackendManifest.payload.database_maintenance_helper
            database_maintenance_helper_smoke =
                $BackendManifest.payload.database_maintenance_helper_smoke
            toolchain = $BackendManifest.toolchain
            manifest = Get-TicketboxFileEvidence $BackendRoot $BackendBuildManifest
        }
        manager = [ordered]@{
            version = $ManagerManifest.version
            source_algorithm = $ManagerManifest.source.algorithm
            source_fingerprint = $ManagerManifest.source.fingerprint
            payload_algorithm = $ManagerManifest.payload.algorithm
            payload_fingerprint = $ManagerManifest.payload.fingerprint
            executable = $ManagerManifest.payload.executable
            toolchain = $ManagerManifest.toolchain
            manifest = Get-TicketboxFileEvidence $RepoRoot $ManagerBuildManifest
        }
        postgresql = [ordered]@{
            version = $PostgresProvenance.version
            version_policy = $PostgresProvenance.version_policy
            major = $PostgresProvenance.major
            version_output = $PostgresProvenance.version_output
            verified_directories = @("bin", "lib", "share")
            payload_algorithm = $PostgresProvenance.bundle_snapshot.algorithm
            payload_fingerprint = $PostgresProvenance.bundle_snapshot.fingerprint
            payload_file_count = @($PostgresProvenance.bundle_snapshot.files).Count
            archive_payload_algorithm = $PostgresProvenance.archive_payload_snapshot.algorithm
            archive_payload_fingerprint = $PostgresProvenance.archive_payload_snapshot.fingerprint
            archive_payload_file_count = @($PostgresProvenance.archive_payload_snapshot.files).Count
            critical_files = @($PostgresProvenance.critical_files)
            bundle_manifest = Get-TicketboxFileEvidence $PgBundle $PgManifest
            license_file = Get-TicketboxFileEvidence $PgBundle (Join-Path $PgBundle "server_license.txt")
            recorded_source_zip = $PostgresProvenance.manifest["source_zip"]
            recorded_source_sha256 = $PostgresProvenance.manifest["source_sha256"].ToLowerInvariant()
            recorded_source_url = $PostgresProvenance.manifest["source_url"]
        }
        shawl = [ordered]@{
            version = $ShawlProvenance.version
            version_policy = $ShawlProvenance.version_policy
            version_output = $ShawlProvenance.version_output
            probes = @($ShawlProvenance.probes)
            executable = $ShawlProvenance.executable
            legal_archive = $ShawlProvenance.legal_archive
            legal_notice = $ShawlProvenance.legal_notice
        }
        visual_cpp_runtime = [ordered]@{
            version = $VisualCppRuntimeProvenance.version
            architecture = $VisualCppRuntimeProvenance.architecture
            runtime_file = $VisualCppRuntimeProvenance.runtime_file
            source_archive = $VisualCppRuntimeProvenance.source_archive
            source_url = $VisualCppRuntimeProvenance.source_url
            executable = $VisualCppRuntimeProvenance.executable
            file_version = $VisualCppRuntimeProvenance.file_version
            product_version = $VisualCppRuntimeProvenance.product_version
            original_filename = $VisualCppRuntimeProvenance.original_filename
            company_name = $VisualCppRuntimeProvenance.company_name
            authenticode = $VisualCppRuntimeProvenance.authenticode
        }
    }
}

function Remove-TicketboxPublishFilesVerified([string[]]$Paths, [string]$AllowedRoot) {
    $failures = @()
    foreach ($path in $Paths) {
        try {
            Assert-TicketboxNoReparsePath -Path $path -AllowedRoot $AllowedRoot | Out-Null
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction Stop
            }
            if (Test-Path -LiteralPath $path) { throw "path still exists" }
        }
        catch {
            $failures += "$path ($($_.Exception.Message))"
        }
    }
    if ($failures.Count -gt 0) {
        throw "无法清除可能陈旧的发布产物：$($failures -join '; ')"
    }
}

function Remove-TicketboxPublishDirectoryVerified([string]$Path, [string]$PublishRoot) {
    $candidate = Assert-TicketboxNoReparsePath `
        -Path $Path `
        -AllowedRoot $PublishRoot `
        -InspectTree
    if (Test-Path -LiteralPath $candidate) {
        Remove-Item -LiteralPath $candidate -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $candidate) {
        throw "无法清除可能陈旧的发布目录：$candidate"
    }
}

function Assert-TicketboxExactJsonProperties(
    [object]$Value,
    [string[]]$ExpectedNames,
    [string]$Label
) {
    if ($null -eq $Value) { throw "$Label 为空。" }
    $actualNames = [string[]]@($Value.PSObject.Properties.Name)
    $expected = [string[]]@($ExpectedNames)
    [Array]::Sort($actualNames, [System.StringComparer]::Ordinal)
    [Array]::Sort($expected, [System.StringComparer]::Ordinal)
    if (($actualNames -join "`n") -cne ($expected -join "`n")) {
        throw "$Label 字段集合不精确：actual=$($actualNames -join ',')"
    }
}

function Assert-TicketboxInstallerCompilerContentManifest {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ExpectedProgramPath
    )
    Assert-File $ManifestPath "ISCC compiler content manifest"
    Assert-File $ExpectedProgramPath "staged database generation program"
    $records = @(Import-Csv -LiteralPath $ManifestPath -Delimiter "`t" -Encoding UTF8)
    if ($records.Count -eq 0) {
        throw "ISCC compiler content manifest is empty."
    }
    $expectedFields = @(
        "Index", "SourceFilename", "TimeStamp", "Version",
        "SHA256Sum", "OriginalSize", "FirstSlice", "LastSlice", "StartOffset",
        "ChunkSuboffset", "ChunkCompressedSize", "Encrypted", "ISSigKeyID"
    )
    Assert-TicketboxExactJsonProperties `
        -Value $records[0] `
        -ExpectedNames $expectedFields `
        -Label "ISCC compiler content manifest row"
    $expectedPath = [System.IO.Path]::GetFullPath($ExpectedProgramPath)
    $programRows = @(
        $records | Where-Object {
            [System.StringComparer]::OrdinalIgnoreCase.Equals(
                [System.IO.Path]::GetFullPath([string]$_.SourceFilename),
                $expectedPath
            )
        }
    )
    if ($programRows.Count -ne 1) {
        throw "ISCC must compile the database generation program exactly once."
    }
    $program = Get-Item -LiteralPath $expectedPath -Force
    $row = $programRows[0]
    if (
        ([string]$row.SHA256Sum).ToLowerInvariant() -cne
            (Get-TicketboxFileSha256 $expectedPath) -or
        [int64]$row.OriginalSize -ne [int64]$program.Length -or
        ([string]$row.Encrypted).ToLowerInvariant() -cne "no"
    ) {
        throw "ISCC compiler content manifest does not bind the exact database generation program bytes."
    }
}

function Assert-TicketboxInstallerPublishUnit {
    param(
        [Parameter(Mandatory = $true)][string]$PublishDirectory,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion,
        [Parameter(Mandatory = $true)][object]$ExpectedCompilerProvenance,
        [Parameter(Mandatory = $true)][object]$ExpectedBuildInputs,
        [Parameter(Mandatory = $true)][string[]]$ExpectedCompilerDefines,
        [string]$ExpectedInstallerSha256 = "",
        [string]$ExpectedDirectoryName = ""
    )
    Assert-Dir $PublishDirectory "安装器发布单元"
    Assert-TicketboxNoReparsePath `
        -Path $PublishDirectory `
        -AllowedRoot (Split-Path -Parent $PublishDirectory) `
        -InspectTree | Out-Null
    $publishItem = Get-Item -LiteralPath $PublishDirectory -Force
    if (($publishItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "安装器发布单元不得是 reparse point：$PublishDirectory"
    }
    if (
        $ExpectedDirectoryName.Length -gt 0 -and
        $publishItem.Name -cne $ExpectedDirectoryName
    ) {
        throw "安装器发布目录名不精确：actual=$($publishItem.Name)，expected=$ExpectedDirectoryName"
    }

    $expectedInstallerName = "Ticketbox-Setup-$ExpectedVersion.exe"
    $expectedNames = [string[]]@(
        "BUILD_COMPLETE.json",
        "BUILD_PROVENANCE.json",
        $expectedInstallerName,
        "$expectedInstallerName.sha256"
    )
    [Array]::Sort($expectedNames, [System.StringComparer]::Ordinal)
    $entries = @(Get-ChildItem -LiteralPath $PublishDirectory -Force)
    if (@($entries | Where-Object { $_.PSIsContainer }).Count -gt 0) {
        throw "安装器发布单元不得包含子目录。"
    }
    if (@($entries | Where-Object {
        ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    }).Count -gt 0) {
        throw "安装器发布单元不得包含 reparse point 文件。"
    }
    $actualNames = [string[]]@($entries | ForEach-Object { $_.Name })
    [Array]::Sort($actualNames, [System.StringComparer]::Ordinal)
    if (($actualNames -join "`n") -cne ($expectedNames -join "`n")) {
        throw "安装器发布单元文件集合不精确：actual=$($actualNames -join ',')"
    }

    $installerPath = Join-Path $PublishDirectory $expectedInstallerName
    $checksumPath = "$installerPath.sha256"
    $provenancePath = Join-Path $PublishDirectory "BUILD_PROVENANCE.json"
    $completionPath = Join-Path $PublishDirectory "BUILD_COMPLETE.json"
    try {
        $completion = Get-Content -LiteralPath $completionPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装器发布完成标记不是有效 JSON：$completionPath。$($_.Exception.Message)"
    }
    Assert-TicketboxExactJsonProperties `
        $completion `
        @(
            "schema",
            "version",
            "installer",
            "installer_sha256",
            "checksum",
            "provenance",
            "provenance_sha256"
        ) `
        "安装器发布完成标记"
    if (
        [string]$completion.schema -cne "ticketbox-installer-publish-v1" -or
        [string]$completion.version -cne $ExpectedVersion -or
        [string]$completion.installer -cne $expectedInstallerName -or
        [string]$completion.checksum -cne "$expectedInstallerName.sha256" -or
        [string]$completion.provenance -cne "BUILD_PROVENANCE.json" -or
        [string]$completion.installer_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$completion.provenance_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "安装器发布完成标记 schema、文件名或 hash 字段无效。"
    }

    $installerHash = Get-TicketboxFileSha256 $installerPath
    $provenanceHash = Get-TicketboxFileSha256 $provenancePath
    if (
        $installerHash -cne [string]$completion.installer_sha256 -or
        $provenanceHash -cne [string]$completion.provenance_sha256
    ) {
        throw "安装器发布完成标记与实际 installer/provenance hash 不一致。"
    }
    if (
        $ExpectedInstallerSha256.Length -gt 0 -and
        $installerHash -cne $ExpectedInstallerSha256.ToLowerInvariant()
    ) {
        throw "安装器发布单元与本轮 ISCC 输出 hash 不一致。"
    }
    $expectedChecksum = "$installerHash  $expectedInstallerName" + [Environment]::NewLine
    $actualChecksum = [System.IO.File]::ReadAllText($checksumPath)
    if ($actualChecksum -cne $expectedChecksum) {
        throw "安装器 SHA-256 旁车内容或格式无效。"
    }
    Assert-TicketboxInstallerBuildProvenance `
        $BackendRoot `
        $provenancePath `
        $ExpectedCompilerProvenance `
        $ExpectedBuildInputs `
        $ExpectedCompilerDefines | Out-Null
    return [pscustomobject]@{
        Path = $publishItem.FullName
        Installer = $installerPath
        InstallerSha256 = $installerHash
        Provenance = $provenancePath
    }
}

function Publish-TicketboxInstallerUnit {
    param(
        [Parameter(Mandatory = $true)][string]$StagingDirectory,
        [Parameter(Mandatory = $true)][string]$TargetDirectory,
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][string]$PublishRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion,
        [Parameter(Mandatory = $true)][object]$ExpectedCompilerProvenance,
        [Parameter(Mandatory = $true)][object]$ExpectedBuildInputs,
        [Parameter(Mandatory = $true)][string[]]$ExpectedCompilerDefines,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallerSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedDirectoryName
    )
    $receiptPath = Join-Path $PublishRoot (".{0}.publish-receipt.json" -f $ExpectedDirectoryName)
    $validateInstallerPublish = {
        param([string]$PublishedDirectory)
        Assert-TicketboxInstallerPublishUnit `
            -PublishDirectory $PublishedDirectory `
            -ExpectedVersion $ExpectedVersion `
            -ExpectedCompilerProvenance $ExpectedCompilerProvenance `
            -ExpectedBuildInputs $ExpectedBuildInputs `
            -ExpectedCompilerDefines $ExpectedCompilerDefines `
            -ExpectedInstallerSha256 $ExpectedInstallerSha256 `
            -ExpectedDirectoryName $ExpectedDirectoryName | Out-Null
    }
    Publish-TicketboxRecoverableDirectory `
        -StagingDirectory $StagingDirectory `
        -TargetDirectory $TargetDirectory `
        -BackupDirectory $BackupDirectory `
        -ReceiptPath $receiptPath `
        -PublishRoot $PublishRoot `
        -ValidatePublished $validateInstallerPublish
}

function Write-InstallerBuildProvenance(
    [object]$BuildInputs,
    [object]$RecipeSnapshot,
    [object]$GitProvenance,
    [object]$CompilerProvenance,
    [string[]]$CompilerDefines,
    [Parameter(Mandatory = $true)][string]$ManifestPath
) {
    if ($null -eq $CompilerProvenance) {
        throw "真实安装器 provenance 必须包含 ISCC identity。"
    }
    $manifest = [ordered]@{
        schema_version = 3
        artifact_type = "ticketbox-windows-installer-inputs"
        build_mode = "installer-build"
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        verification_scope = "build-time-local-payload-integrity-only"
        upstream_authenticity_verified = $false
        trust_note = "Hashes and executable probes bind the local build inputs; they do not establish upstream publisher authenticity."
        git = [ordered]@{
            commit = $GitProvenance.commit
            dirty = $GitProvenance.dirty
            status_entry_count = $GitProvenance.status_entry_count
            status_fingerprint = $GitProvenance.status_fingerprint
        }
        recipe = $RecipeSnapshot
        compiler = [ordered]@{
            included = $true
            product_name = $CompilerProvenance.product_name
            product_version = $CompilerProvenance.product_version
            file_version = $CompilerProvenance.file_version
            engine_version = $CompilerProvenance.engine_version
            version_policy = $CompilerProvenance.version_policy
            executable = $CompilerProvenance.executable
        }
        compiler_defines = @(Get-TicketboxNormalizedCompilerDefines $CompilerDefines)
        backend = $BuildInputs.backend
        manager = $BuildInputs.manager
        postgresql = $BuildInputs.postgresql
        shawl = $BuildInputs.shawl
    }
    Write-TicketboxJsonFile $ManifestPath $manifest
    return [pscustomobject]@{
        Path = $ManifestPath
        Manifest = $manifest
    }
}

function Resolve-VersionInfoVersion([string]$Value) {
    $parts = @(ConvertTo-SupportedNumericVersionParts $Value)
    return ($parts -join ".")
}

function ConvertTo-SupportedNumericVersionParts([string]$Value) {
    $match = [regex]::Match(
        $Value,
        '^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})(?:\.(0|[1-9][0-9]{0,4}))?$'
    )
    if (-not $match.Success) {
        throw "安装器版本必须遵守三段或四段纯数字契约，才能安全比较并阻止降级：$Value"
    }
    $parts = @()
    foreach ($index in 1..4) {
        if ($match.Groups[$index].Success -and [int64]$match.Groups[$index].Value -gt 65535) {
            throw "安装器数字版本分量不能超过 65535：$Value"
        }
        if ($match.Groups[$index].Success) {
            $parts += [int]$match.Groups[$index].Value
        }
        else {
            $parts += 0
        }
    }
    return $parts
}

function Compare-SupportedNumericVersions([string]$LeftValue, [string]$RightValue) {
    $left = @(ConvertTo-SupportedNumericVersionParts $LeftValue)
    $right = @(ConvertTo-SupportedNumericVersionParts $RightValue)
    foreach ($index in 0..3) {
        if ($left[$index] -lt $right[$index]) { return -1 }
        if ($left[$index] -gt $right[$index]) { return 1 }
    }
    return 0
}

function Assert-SupportedNumericInstallerVersion([string]$Value) {
    ConvertTo-SupportedNumericVersionParts $Value | Out-Null
}

function Invoke-VersionFloorContractProbe([string]$Value) {
    $parts = @($Value.Split([char]"|"))
    if ($parts.Count -notin @(4, 5) -or $parts[0].Trim().Length -eq 0) {
        throw "版本下限 probe 必须是 target|persistent|machine|legacy|existing（旧四段格式仍可用于无 machine 投影的测试）。"
    }
    $target = $parts[0].Trim()
    $persistent = $parts[1].Trim()
    if ($parts.Count -eq 5) {
        $machine = $parts[2].Trim()
        $legacy = $parts[3].Trim()
        $existingText = $parts[4].Trim().ToLowerInvariant()
    }
    else {
        $machine = ""
        $legacy = $parts[2].Trim()
        $existingText = $parts[3].Trim().ToLowerInvariant()
    }
    if ($existingText -notin @("true", "false")) {
        throw "版本下限 probe 的 existing 必须是 true 或 false。"
    }
    $existing = $existingText -eq "true"
    $floor = ""
    foreach ($candidate in @($persistent, $machine)) {
        if ($candidate.Length -eq 0) { continue }
        Assert-SupportedNumericInstallerVersion $candidate
        if ($floor.Length -eq 0 -or (Compare-SupportedNumericVersions $candidate $floor) -gt 0) {
            $floor = $candidate
        }
    }
    if ($floor.Length -eq 0 -and $legacy.Length -gt 0) {
        $floor = $legacy
    }
    elseif ($floor.Length -eq 0 -and $existing) {
        throw "现有安装缺少可信版本下限。"
    }
    elseif ($floor.Length -eq 0) {
        Assert-SupportedNumericInstallerVersion $target
        return "fresh"
    }
    if ((Compare-SupportedNumericVersions $target $floor) -lt 0) {
        throw "拒绝降级：target=$target，floor=$floor"
    }
    return "allow"
}

function Invoke-VersionPolicyContractProbe([string]$Value) {
    $parts = @($Value.Split([char]"|"))
    if ($parts.Count -ne 2 -or $parts[0].Trim().Length -eq 0 -or $parts[1].Trim().Length -eq 0) {
        throw "依赖版本策略 probe 必须是 vendor|version。"
    }
    Assert-File $ReleaseConfigScript "Windows release config 解析脚本"
    . $ReleaseConfigScript
    $probeConfig = Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath
    $policy = Assert-TicketboxVendorVersionAllowed $probeConfig $parts[0].Trim() $parts[1].Trim()
    return "allow [$($policy.minimum), $($policy.maximum_exclusive))"
}

Assert-File $BuildProvenanceScript "Windows build provenance helper"
. $BuildProvenanceScript
if ($ReleaseConfigOverride.Trim().Length -gt 0 -and $VersionPolicyContractProbe.Trim().Length -eq 0) {
    throw "-ReleaseConfigOverride 只允许与 -VersionPolicyContractProbe 一起用于测试动态版本策略。"
}
$activeVersionProbes = @(
    $VersionContractProbe,
    $VersionFloorContractProbe,
    $VersionPolicyContractProbe
) | Where-Object { $_.Trim().Length -gt 0 }
if (@($activeVersionProbes).Count -gt 1) {
    throw "版本 probe 不能同时使用。"
}
if ($VersionContractProbe.Trim().Length -gt 0) {
    Write-Output (Resolve-VersionInfoVersion $VersionContractProbe)
    return
}
if ($VersionFloorContractProbe.Trim().Length -gt 0) {
    Write-Output (Invoke-VersionFloorContractProbe $VersionFloorContractProbe)
    return
}
if ($VersionPolicyContractProbe.Trim().Length -gt 0) {
    Write-Output (Invoke-VersionPolicyContractProbe $VersionPolicyContractProbe)
    return
}
Assert-File $ManagerBuildProvenanceScript "Windows Desktop Manager build provenance helper"
. $ManagerBuildProvenanceScript

$activeBuildModes = @(
    [bool]$CheckSourceInputsOnly,
    [bool]$CheckInputsOnly,
    [bool]$VerifyOnly
) | Where-Object { $_ }
if (@($activeBuildModes).Count -gt 1) {
    throw "-CheckSourceInputsOnly、-CheckInputsOnly 与 -VerifyOnly 不能同时使用。"
}

function Write-TicketboxInstallerHashOutput {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallerSha256,
        [Parameter(Mandatory = $true)][string]$PublishRoot
    )
    if ($InstallerSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "installer hash output 不是规范 SHA-256。"
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullPublishRoot = [System.IO.Path]::GetFullPath($PublishRoot).TrimEnd("\\")
    $publishPrefix = $fullPublishRoot + [System.IO.Path]::DirectorySeparatorChar
    if ($fullPath.Equals(
        $fullPublishRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or $fullPath.StartsWith(
        $publishPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "installer hash output 必须位于 publish unit 之外。"
    }
    $parent = Split-Path -Parent $fullPath
    Assert-Dir $parent "installer hash output 父目录"
    if ((Test-Path -LiteralPath $fullPath) -and -not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "installer hash output 不是普通文件：$fullPath"
    }
    $line = "installer_sha256=$InstallerSha256" + [Environment]::NewLine
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($line)
    $stream = [System.IO.File]::Open(
        $fullPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::Read
    )
    try {
        [void]$stream.Seek(0, [System.IO.SeekOrigin]::End)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}
if ($VerifyPublishDirectory.Trim().Length -gt 0 -and -not $VerifyOnly) {
    throw "VerifyPublishDirectory 只允许用于 VerifyOnly。"
}
if ($InstallerHashOutputFile.Trim().Length -gt 0 -and @($activeBuildModes).Count -gt 0) {
    throw "InstallerHashOutputFile 只允许用于真实编译模式。"
}

$BuildLock = $null
$InstallerPrimaryFailure = $null
$InstallerCleanupFailures = New-Object System.Collections.Generic.List[string]
try {
if (-not $CheckSourceInputsOnly) {
    $BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot
}
$resolvedVersion = Resolve-Version
Assert-SupportedNumericInstallerVersion $resolvedVersion
$resolvedVersionInfo = Resolve-VersionInfoVersion $resolvedVersion
$publishRoot = Join-Path $BackendRoot "dist\installer"
$publishUnitName = "Ticketbox-Setup-$resolvedVersion"
$targetPublishDir = Join-Path $publishRoot $publishUnitName
if ($VerifyPublishDirectory.Trim().Length -gt 0) {
    $targetPublishDir = [System.IO.Path]::GetFullPath($VerifyPublishDirectory)
    $publishRoot = Split-Path -Parent $targetPublishDir
}
$publishNonce = "{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N")
$publishBackupDir = Join-Path $publishRoot (".$publishUnitName.last-known-good")
$publishReceipt = Join-Path $publishRoot (".$publishUnitName.publish-receipt.json")
$installerFileName = "$publishUnitName.exe"
$targetInstaller = Join-Path $targetPublishDir $installerFileName
$targetChecksum = "$targetInstaller.sha256"
$targetManifest = Join-Path $targetPublishDir "BUILD_PROVENANCE.json"
$targetCompletion = Join-Path $targetPublishDir "BUILD_COMPLETE.json"
$legacyInstaller = Join-Path $publishRoot $installerFileName
$legacyChecksum = "$legacyInstaller.sha256"
if (
    -not $CheckSourceInputsOnly -and
    -not $CheckInputsOnly -and
    $VerifyPublishDirectory.Trim().Length -eq 0
) {
    Assert-TicketboxNoReparsePath -Path $publishRoot -AllowedRoot $BackendRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $publishRoot | Out-Null
    Recover-TicketboxDirectoryPublication `
        -TargetDirectory $targetPublishDir `
        -BackupDirectory $publishBackupDir `
        -ReceiptPath $publishReceipt `
        -PublishRoot $publishRoot
}

Write-Step "校验 Inno 安装器输入"
Assert-File $IssPath "Inno 脚本"
Assert-File $IssWindowsCode "Inno Windows runtime include"
Assert-File $IssFlowCode "Inno installer flow include"
Assert-File $ChineseLanguageFile "Inno 简体中文语言文件"
Assert-File $ReleaseConfigScript "Windows release config 解析脚本"
Assert-File $BuildProvenanceScript "Windows installer build provenance 脚本"
Assert-File $BackendBuildProvenanceScript "Windows backend build provenance 脚本"
Assert-File $ManagerBuildProvenanceScript "Windows Desktop Manager build provenance 脚本"
Assert-File $BuildToolchainPrepScript "Windows build toolchain 准备脚本"
. $ReleaseConfigScript
$releaseConfig = Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath
$installerVendorContracts = Read-TicketboxInstallerVendorContracts $ToolchainConfigPath
$ShawlLegalNotice = Join-Path `
    (Split-Path -Parent $ShawlExe) `
    ([string]$installerVendorContracts.shawl.legal.notice_name)
$buildToolchainContract = Read-TicketboxWindowsBuildToolchain $BackendRoot
Get-TicketboxVendorVersionPolicy $releaseConfig "postgres" | Out-Null
Get-TicketboxVendorVersionPolicy $releaseConfig "shawl" | Out-Null
Get-TicketboxVendorVersionPolicy $releaseConfig "iscc" | Out-Null
Assert-File $PrepareScript "升级前预检脚本"
Assert-File $ServiceContractScript "Windows 服务命令契约脚本"
Assert-File $ServiceIdentityScript "Windows 服务身份契约脚本"
Assert-File $LifecycleScript "Windows 服务生命周期脚本"
Assert-File $SafetyScript "Windows 安装安全脚本"
Assert-File $ReceiptScript "Windows 生命周期回执脚本"
Assert-File $LockScript "Windows 生命周期锁脚本"
Assert-File $LockHolderScript "Windows 生命周期锁 holder 脚本"
Assert-File $DataRootGuardScript "Windows DataRoot guard holder 脚本"
Assert-File $DatabaseSafetyScript "Windows 数据库安全脚本"
Assert-File $PgRecoveryToolsScript "Windows PostgreSQL 恢复工具脚本"
Assert-File `
    $PostgresqlDatabaseCatalogScript `
    "Windows PostgreSQL database-catalog adapter"
Assert-File `
    $PostgresqlDatabaseCatalogPrimitivesScript `
    "Windows PostgreSQL database-catalog primitives"
Assert-File `
    $PostgresqlDatabaseCatalogQueryScript `
    "Windows PostgreSQL database-catalog query"
Assert-File `
    $PostgresqlDatabaseCatalogCodecScript `
    "Windows PostgreSQL database-catalog codec"
Assert-File `
    $PostgresqlDatabaseCatalogObservationScript `
    "Windows PostgreSQL database-catalog observation"
Assert-File `
    $PostgresqlWriterFenceScript `
    "Windows PostgreSQL writer-fence adapter"
Assert-File `
    $PostgresqlWriterFencePrimitivesScript `
    "Windows PostgreSQL writer-fence primitives"
Assert-File `
    $PostgresqlWriterFenceObservationQueryScript `
    "Windows PostgreSQL writer-fence observation query"
Assert-File `
    $PostgresqlWriterFenceObservationCodecScript `
    "Windows PostgreSQL writer-fence observation codec"
Assert-File `
    $PostgresqlWriterFenceObservationScript `
    "Windows PostgreSQL writer-fence observation adapter"
Assert-File `
    $PostgresqlWriterFenceReconcilePolicyScript `
    "Windows PostgreSQL writer-fence reconcile policy"
Assert-File `
    $PostgresqlWriterFencePreconditionGuardScript `
    "Windows PostgreSQL writer-fence precondition guard"
Assert-File `
    $PostgresqlWriterFenceSessionDrainScript `
    "Windows PostgreSQL writer-fence session drain"
Assert-File `
    $PostgresqlWriterFenceReconcilerScript `
    "Windows PostgreSQL writer-fence reconciler"
Assert-File $DatabaseScript "Windows bundled database 脚本"
Assert-File `
    $PostgresqlDatabaseCommandScript `
    "Windows PostgreSQL database command adapter"
Assert-File `
    $TicketboxDatabaseContractScript `
    "Ticketbox database authorization contract"
Assert-File $TicketboxDatabaseAclScript "Ticketbox database ACL policy"
Assert-File $TicketboxDatabaseRolesScript "Ticketbox database role policy"
Assert-File $WindowsSecurityPrimitivesScript "Windows security primitives 脚本"
Assert-File $WindowsSecurityByteArrayScript "Windows security byte-array primitives 脚本"
Assert-File `
    $WindowsSecurityTokenPrivilegeNativeScript `
    "Windows native token privilege primitives 脚本"
Assert-File $WindowsSecurityTokenPrivilegeScript "Windows token privilege primitives 脚本"
Assert-File `
    $WindowsSecurityDescriptorComparisonScript `
    "Windows security descriptor comparison primitives 脚本"
Assert-File `
    $WindowsSecurityDescriptorDiagnosticScript `
    "Windows security descriptor diagnostic primitives 脚本"
Assert-File $WindowsSecurityFileSecurityScript "Windows file-security primitives 脚本"
Assert-File $PostgresqlCredentialsScript "Windows PostgreSQL credential primitives"
Assert-File $PostgresqlSingleUserScript "Windows PostgreSQL single-user service adapter"
Assert-File $WindowsDeadlineBudgetScript "Windows deadline-budget adapter"
Assert-File $AtomicArtifactsScript "Windows atomic-artifact 入口脚本"
Assert-File $AtomicArtifactsNativeScript "Windows atomic-artifact native 脚本"
Assert-File $AtomicArtifactsFileScript "Windows atomic-artifact file 脚本"
Assert-File $AtomicArtifactsDirectoryScript "Windows atomic-artifact directory 脚本"
Assert-File $DatabaseGenerationProgramAdapterScript "Windows database generation program adapter"
Assert-File `
    $DatabaseGenerationProgramExecutionScript `
    "Windows database generation program execution"
Assert-File $DatabaseGenerationScript "Windows database generation owner"
Assert-File $DatabaseGenerationContractScript "Windows database generation contract"
Assert-File $DatabaseGenerationArtifactsScript "Windows database generation artifact store"
Assert-File `
    $DatabaseGenerationCommitVerifierScript `
    "Windows database generation commit verifier"
Assert-File $DatabaseGenerationPolicyScript "Windows database generation policy"
Assert-File $DatabaseGenerationCredentialsScript "Windows database generation credentials"
Assert-File $DatabaseGenerationRoleFenceScript "Windows database generation role fence"
Assert-File `
    $DatabaseGenerationDatabaseBindingScript `
    "Windows database generation database binding"
Assert-File $DatabaseGenerationSourceScript "Windows database generation source mechanism"
Assert-File `
    $DatabaseGenerationRecoveryEvidenceScript `
    "Windows database generation recovery evidence"
Assert-File `
    $DatabaseGenerationTargetRecoveryScript `
    "Windows database generation fixed target recovery"
Assert-File `
    $DatabaseGenerationRetirementScript `
    "Windows database generation bootstrap retirement"
Assert-File `
    $DatabaseGenerationSingleUserScript `
    "Windows database generation single-user helper"
Assert-File `
    $DatabaseGenerationProjectionScript `
    "Windows database generation runtime projection"
Assert-File $BackendBootstrapScript "Windows 后端就绪/bootstrap 脚本"
Assert-File $BootstrapExposureRecoveryScript "Windows bootstrap 暴露恢复脚本"
Assert-File $InstallScript "install_bundled_services.ps1"
Assert-File $UninstallScript "uninstall_bundled_services.ps1"
Assert-File $WindowsPrerequisiteScript "Windows prerequisite 安装脚本"
Write-Ok "输入齐备。"

Write-Ok "安装包版本：$resolvedVersion"
Write-Ok "Windows 文件版本：$resolvedVersionInfo"
if ($CheckSourceInputsOnly) {
    $sourceSnapshot = Get-TicketboxBackendSourceSnapshot $BackendRoot
    Write-Ok "当前冻结相关源码指纹：$($sourceSnapshot.fingerprint)"
    $managerSourceSnapshot = Get-TicketboxManagerSourceSnapshot $RepoRoot
    Write-Ok "当前 Desktop Manager 源码指纹：$($managerSourceSnapshot.fingerprint)"
    $recipeSnapshot = Get-TicketboxInstallerRecipeSnapshot $BackendRoot
    Write-Ok "当前安装器配方指纹：$($recipeSnapshot.fingerprint)"
    $gitProvenance = Get-TicketboxGitProvenance $BackendRoot
    Write-Ok "Git provenance：$($gitProvenance.commit) dirty=$($gitProvenance.dirty)"
    Write-Host ""
    Write-Host "CheckSourceInputsOnly OK（仅验证受版本控制的安装器源码/配置；未验证 frozen dist、vendor 或 ISCC，不代表安装包构建成功）。" -ForegroundColor Green
    return
}
$sourceSnapshot = Get-TicketboxBackendSourceSnapshot $BackendRoot
Write-Ok "当前冻结相关源码指纹：$($sourceSnapshot.fingerprint)"
$managerSourceSnapshot = Get-TicketboxManagerSourceSnapshot $RepoRoot
Write-Ok "当前 Desktop Manager 源码指纹：$($managerSourceSnapshot.fingerprint)"
$recipeSnapshot = Get-TicketboxInstallerRecipeSnapshot $BackendRoot
Write-Ok "当前安装器配方指纹：$($recipeSnapshot.fingerprint)"
$gitProvenance = Get-TicketboxGitProvenance $BackendRoot
Write-Ok "Git provenance：$($gitProvenance.commit) dirty=$($gitProvenance.dirty)"
Assert-Dir $BackendDist "冻结后端 onedir"
Assert-TicketboxNoReparsePath -Path $BackendDist -AllowedRoot $BackendRoot -InspectTree | Out-Null
Assert-File (Join-Path $BackendDist "ticketbox-backend.exe") "ticketbox-backend.exe"
Assert-File (Join-Path $BackendDist "ticketbox-database-maintenance.exe") "ticketbox-database-maintenance.exe"
$backendManifest = Assert-TicketboxBackendBuildManifest $BackendRoot $BackendDist
Write-Ok "冻结后端 manifest 已绑定当前源码、版本和 EXE/payload hash。"
Assert-Dir $ManagerDist "冻结 Desktop Manager onedir"
Assert-TicketboxNoReparsePath -Path $ManagerDist -AllowedRoot $RepoRoot -InspectTree | Out-Null
Assert-File (Join-Path $ManagerDist "ticketbox-manager.exe") "ticketbox-manager.exe"
$managerManifest = Assert-TicketboxManagerBuildManifest $RepoRoot $ManagerDist
Write-Ok "冻结 Desktop Manager manifest 已绑定当前源码、版本和 EXE/payload hash。"
Assert-Dir $PgBundle "捆绑 PostgreSQL"
Assert-TicketboxNoReparsePath -Path $PgBundle -AllowedRoot $BackendRoot -InspectTree | Out-Null
$postgresProvenance = Get-ValidatedPostgresProvenance
Write-Ok "PostgreSQL 探针：$($postgresProvenance.version_output)"
$shawlProvenance = Get-ValidatedShawlProvenance
Write-Ok "Shawl 探针：$($shawlProvenance.version_output)"
Assert-TicketboxNoReparsePath `
    -Path $VisualCppRuntimeExe `
    -AllowedRoot $BackendRoot | Out-Null
$visualCppRuntimeProvenance = Get-ValidatedVisualCppRuntimeProvenance
Write-Ok (
    "Microsoft Visual C++ runtime：version={0} sha256={1} signer={2}" -f `
        $visualCppRuntimeProvenance.version,
        $visualCppRuntimeProvenance.executable.sha256,
        $visualCppRuntimeProvenance.authenticode.signer_thumbprint
)
if ($CheckInputsOnly) {
    Write-Host ""
    Write-Host "CheckInputsOnly OK（未生成安装器 provenance；真实构建必须探测 ISCC identity）。" -ForegroundColor Green
    return
}
if ($InnoCompiler.Trim().Length -eq 0) {
    & $BuildToolchainPrepScript -Component Inno
    $InnoCompiler = Join-Path `
        $BackendRoot `
        ("build\windows-toolchain\inno\{0}" -f [string]$buildToolchainContract.inno_source.compiler_relative_path)
}
$iscc = Find-Iscc
if (-not $iscc) {
    throw "固定 Windows 构建工具链未提供 ISCC.exe，拒绝使用机器隐式安装。"
}
$isccProvenance = Get-TicketboxIsccProvenance $iscc
if (
    $isccProvenance.engine_version -cne [string]$buildToolchainContract.inno_source.version -or
    $isccProvenance.executable.sha256 -cne
        ([string]$buildToolchainContract.inno_source.compiler_sha256).ToLowerInvariant()
) {
    throw "ISCC identity 与固定官方归档合同不一致。"
}
$isccProvenance | Add-Member `
    -NotePropertyName version_policy `
    -NotePropertyValue (Assert-TicketboxVendorVersionAllowed `
        $releaseConfig `
        "iscc" `
        $isccProvenance.engine_version)
Write-Ok "ISCC identity：engine=$($isccProvenance.engine_version) / sha256=$($isccProvenance.executable.sha256)"
$pgDumpBuildEvidence = @($postgresProvenance.critical_files | Where-Object {
    [string]$_.path -ceq "bin/pg_dump.exe"
})
$pgRestoreBuildEvidence = @($postgresProvenance.critical_files | Where-Object {
    [string]$_.path -ceq "bin/pg_restore.exe"
})
if ($pgDumpBuildEvidence.Count -ne 1 -or $pgRestoreBuildEvidence.Count -ne 1) {
    throw "PostgreSQL build provenance 未唯一绑定 pg_dump/pg_restore。"
}
$defines = @(
    "/DAppVersion=$resolvedVersion",
    "/DAppVersionInfo=$resolvedVersionInfo",
    "/DPgServiceName=$($releaseConfig.pg_service_name)",
    "/DBackendServiceName=$($releaseConfig.backend_service_name)",
    "/DDefaultPgPort=$($releaseConfig.default_pg_port)",
    "/DFallbackPgPort=$($releaseConfig.fallback_pg_port)",
    "/DDefaultBackendPort=$($releaseConfig.default_backend_port)",
    "/DFallbackBackendPort=$($releaseConfig.fallback_backend_port)",
    "/DTargetPgMajor=$($postgresProvenance.major)",
    "/DLifecycleSafetyScriptSha256=$(Get-TicketboxFileSha256 $SafetyScript)",
    "/DWindowsSecurityPrimitivesScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityPrimitivesScript)",
    "/DWindowsSecurityByteArrayScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityByteArrayScript)",
    "/DWindowsSecurityTokenPrivilegeNativeScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityTokenPrivilegeNativeScript)",
    "/DWindowsSecurityTokenPrivilegeScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityTokenPrivilegeScript)",
    "/DWindowsSecurityDescriptorComparisonScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityDescriptorComparisonScript)",
    "/DWindowsSecurityDescriptorDiagnosticScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityDescriptorDiagnosticScript)",
    "/DWindowsSecurityFileSecurityScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityFileSecurityScript)",
    "/DLifecycleLockScriptSha256=$(Get-TicketboxFileSha256 $LockScript)",
    "/DLifecycleHolderScriptSha256=$(Get-TicketboxFileSha256 $LockHolderScript)",
    "/DDataRootGuardScriptSha256=$(Get-TicketboxFileSha256 $DataRootGuardScript)",
    "/DWindowsPrerequisiteScriptSha256=$(Get-TicketboxFileSha256 $WindowsPrerequisiteScript)",
    "/DVisualCppRuntimeVersion=$($visualCppRuntimeProvenance.version)",
    "/DVisualCppRuntimeSha256=$($visualCppRuntimeProvenance.executable.sha256)",
    "/DPrepareScriptSha256=$(Get-TicketboxFileSha256 $PrepareScript)",
    "/DServiceContractScriptSha256=$(Get-TicketboxFileSha256 $ServiceContractScript)",
    "/DServiceIdentityScriptSha256=$(Get-TicketboxFileSha256 $ServiceIdentityScript)",
    "/DServiceLifecycleScriptSha256=$(Get-TicketboxFileSha256 $LifecycleScript)",
    "/DLifecycleReceiptScriptSha256=$(Get-TicketboxFileSha256 $ReceiptScript)",
    "/DDatabaseSafetyScriptSha256=$(Get-TicketboxFileSha256 $DatabaseSafetyScript)",
    "/DPgRecoveryToolsScriptSha256=$(Get-TicketboxFileSha256 $PgRecoveryToolsScript)",
    "/DReleaseConfigScriptSha256=$(Get-TicketboxFileSha256 $ReleaseConfigScript)",
    "/DReleaseConfigJsonSha256=$(Get-TicketboxFileSha256 $ReleaseConfigPath)",
    "/DBuildProvenanceScriptSha256=$(Get-TicketboxFileSha256 $BuildProvenanceScript)",
    "/DBackendBuildProvenanceScriptSha256=$(Get-TicketboxFileSha256 $BackendBuildProvenanceScript)",
    "/DDatabaseGenerationScriptSha256=$(Get-TicketboxFileSha256 $DatabaseGenerationScript)",
    "/DDatabaseGenerationContractScriptSha256=$(Get-TicketboxFileSha256 $DatabaseGenerationContractScript)",
    "/DDatabaseGenerationArtifactsScriptSha256=$(Get-TicketboxFileSha256 $DatabaseGenerationArtifactsScript)",
    "/DDatabaseGenerationCommitVerifierScriptSha256=$(Get-TicketboxFileSha256 $DatabaseGenerationCommitVerifierScript)",
    "/DDatabaseGenerationPolicyScriptSha256=$(Get-TicketboxFileSha256 $DatabaseGenerationPolicyScript)",
    "/DDatabaseGenerationProgramSha256=$([string]$backendManifest.payload.database_generation_program.sha256)",
    "/DDatabaseMaintenanceHelperSize=$([int64]$backendManifest.payload.database_maintenance_helper.size)",
    "/DDatabaseMaintenanceHelperSha256=$([string]$backendManifest.payload.database_maintenance_helper.sha256)",
    "/DDatabaseGenerationPgDumpSize=$([int64]$pgDumpBuildEvidence[0].size)",
    "/DDatabaseGenerationPgDumpSha256=$([string]$pgDumpBuildEvidence[0].sha256)",
    "/DDatabaseGenerationPgRestoreSize=$([int64]$pgRestoreBuildEvidence[0].size)",
    "/DDatabaseGenerationPgRestoreSha256=$([string]$pgRestoreBuildEvidence[0].sha256)"
)
$verifiedBuildInputs = Get-InstallerBuildInputEvidence `
    $backendManifest `
    $managerManifest `
    $postgresProvenance `
    $shawlProvenance `
    $visualCppRuntimeProvenance
if ($VerifyOnly) {
    if ($ExpectedInstallerSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "VerifyOnly 必须提供由本轮编译步骤外部保存的 ExpectedInstallerSha256。"
    }
    $expectedVerifyDirectoryName = if ($VerifyPublishDirectory.Trim().Length -eq 0) {
        $publishUnitName
    }
    else {
        ""
    }
    $verifiedPublish = Assert-TicketboxInstallerPublishUnit `
        -PublishDirectory $targetPublishDir `
        -ExpectedVersion $resolvedVersion `
        -ExpectedCompilerProvenance $isccProvenance `
        -ExpectedBuildInputs $verifiedBuildInputs `
        -ExpectedCompilerDefines $defines `
        -ExpectedInstallerSha256 $ExpectedInstallerSha256.ToLowerInvariant() `
        -ExpectedDirectoryName $expectedVerifyDirectoryName
    Write-Ok "安装器发布单元验证通过：$($verifiedPublish.Path)"
    return
}
$buildStagingRoot = Join-Path $BackendRoot ("dist\.installer-build-{0}" -f $publishNonce)
$stagedRepoRoot = Join-Path $buildStagingRoot "source"
$stagedBackendRoot = Join-Path $stagedRepoRoot "backend"
$stagedScriptDir = Join-Path $stagedBackendRoot "packaging"
$stagedIssPath = Join-Path $stagedScriptDir "ticketbox-installer.iss"
$stagedBackendDist = Join-Path $stagedBackendRoot "dist\ticketbox-backend"
$stagedManagerDist = Join-Path $stagedRepoRoot "desktop\dist\ticketbox-manager"
$stagedPgBundle = Join-Path $stagedScriptDir "vendor\pg"
$stagedShawlExe = Join-Path $stagedScriptDir "vendor\shawl\shawl.exe"
$stagedShawlLegalNotice = Join-Path `
    (Split-Path -Parent $stagedShawlExe) `
    ([string]$installerVendorContracts.shawl.legal.notice_name)
$stagedVisualCppRuntimeExe = Join-Path `
    $stagedScriptDir `
    "vendor\vc-runtime\vc_redist.x64.exe"
$stagedInstallerInputDir = Join-Path $stagedBackendRoot "dist\installer-input"
$stagedInstallerManifest = Join-Path $stagedInstallerInputDir "BUILD_PROVENANCE.json"
$compilerOutputDir = Join-Path $buildStagingRoot "compiler-output"
$stagedInstaller = Join-Path $compilerOutputDir $installerFileName
$stagedCompilerContentManifest = Join-Path $compilerOutputDir "ticketbox-installer-content.tsv"
$publishStagingDir = Join-Path $publishRoot (".$publishUnitName.staging-$publishNonce")
$inputLocks = $null
$isccLocks = $null
$BuildBodyFailure = $null
try {
    Assert-TicketboxNoReparsePath -Path $buildStagingRoot -AllowedRoot (Join-Path $BackendRoot "dist") | Out-Null
    Assert-TicketboxNoReparsePath -Path $publishStagingDir -AllowedRoot $publishRoot | Out-Null
    New-Item -ItemType Directory -Force -Path `
        $stagedBackendRoot, `
        $stagedBackendDist, `
        $stagedManagerDist, `
        $stagedPgBundle, `
        (Split-Path -Parent $stagedShawlExe), `
        (Split-Path -Parent $stagedVisualCppRuntimeExe), `
        $stagedInstallerInputDir, `
        $compilerOutputDir, `
        $publishStagingDir | Out-Null
    Copy-TicketboxFileSetSnapshot `
        -SourceRoot $BackendRoot `
        -DestinationRoot $stagedBackendRoot `
        -Snapshot $recipeSnapshot | Out-Null
    Copy-Item -Path (Join-Path $BackendDist "*") -Destination $stagedBackendDist -Recurse -Force
    Copy-Item -Path (Join-Path $ManagerDist "*") -Destination $stagedManagerDist -Recurse -Force
    Copy-Item -Path (Join-Path $PgBundle "*") -Destination $stagedPgBundle -Recurse -Force
    Copy-Item -LiteralPath $ShawlExe -Destination $stagedShawlExe
    Copy-Item -LiteralPath $ShawlLegalNotice -Destination $stagedShawlLegalNotice
    Copy-Item `
        -LiteralPath $VisualCppRuntimeExe `
        -Destination $stagedVisualCppRuntimeExe

    Assert-TicketboxFileSetSnapshot `
        "安装器 staging 配方" `
        $recipeSnapshot `
        (Get-TicketboxInstallerRecipeSnapshot $stagedBackendRoot)
    Assert-TicketboxBackendBuildManifest $BackendRoot $stagedBackendDist | Out-Null
    Assert-TicketboxManagerBuildManifest $RepoRoot $stagedManagerDist | Out-Null
    Assert-TicketboxStructuredEvidence `
        "安装器 staging PostgreSQL" `
        $postgresProvenance `
        (Get-ValidatedPostgresProvenance $stagedPgBundle)
    Assert-TicketboxStructuredEvidence `
        "安装器 staging Shawl" `
        $shawlProvenance `
        (Get-ValidatedShawlProvenance `
            -ExecutablePath $stagedShawlExe `
            -LegalNoticePath $stagedShawlLegalNotice)
    Assert-TicketboxStructuredEvidence `
        "安装器 staging Microsoft Visual C++ runtime" `
        $visualCppRuntimeProvenance `
        (Get-ValidatedVisualCppRuntimeProvenance $stagedVisualCppRuntimeExe)

    $buildInputs = $verifiedBuildInputs
    $installerBuild = Write-InstallerBuildProvenance `
        $buildInputs `
        $recipeSnapshot `
        $gitProvenance `
        $isccProvenance `
        $defines `
        -ManifestPath $stagedInstallerManifest
    Assert-TicketboxInstallerBuildProvenance $BackendRoot $installerBuild.Path $isccProvenance $buildInputs $defines | Out-Null
    Write-Ok "安装器输入 provenance：$($installerBuild.Path)"

    $stagedInputPaths = @(
        Get-ChildItem -LiteralPath $stagedRepoRoot -Recurse -File |
            ForEach-Object { $_.FullName }
    )
    $stagedInputSnapshot = Get-TicketboxFileSetSnapshot $stagedRepoRoot $stagedInputPaths
    $inputLocks = @(Enter-TicketboxFileSetReadLocks `
        -Root $stagedRepoRoot `
        -Snapshot $stagedInputSnapshot)
    $isccRoot = Split-Path -Parent $iscc
    $isccPaths = @(
        Get-ChildItem -LiteralPath $isccRoot -Recurse -File -Force |
            ForEach-Object { $_.FullName }
    )
    $isccSnapshot = Get-TicketboxFileSetSnapshot $isccRoot $isccPaths
    $isccLocks = @(Enter-TicketboxFileSetReadLocks `
        -Root $isccRoot `
        -Snapshot $isccSnapshot)

    Write-Step "调用 ISCC.exe"
    & $iscc @defines "/O$compilerOutputDir" $stagedIssPath
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC.exe 编译失败（exit=$LASTEXITCODE）。"
    }
    Assert-File $stagedInstaller "本轮 ISCC staging 安装包输出"
    Assert-TicketboxInstallerCompilerContentManifest `
        -ManifestPath $stagedCompilerContentManifest `
        -ExpectedProgramPath (Join-Path $stagedBackendDist "DATABASE_GENERATION_PROGRAM.json")
    Assert-TicketboxFileSetSnapshot `
        "ISCC 实际读取的 staging 输入" `
        $stagedInputSnapshot `
        (Get-TicketboxFileSetSnapshot $stagedRepoRoot $stagedInputPaths)
    Assert-TicketboxFileSetSnapshot `
        "ISCC compiler tree during build" `
        $isccSnapshot `
        (Get-TicketboxFileSetSnapshot $isccRoot $isccPaths)

    $currentBackendManifest = Assert-TicketboxBackendBuildManifest $BackendRoot $BackendDist
    $currentManagerManifest = Assert-TicketboxManagerBuildManifest $RepoRoot $ManagerDist
    $currentPostgresProvenance = Get-ValidatedPostgresProvenance
    $currentShawlProvenance = Get-ValidatedShawlProvenance
    $currentVisualCppRuntimeProvenance = Get-ValidatedVisualCppRuntimeProvenance
    $currentBuildInputs = Get-InstallerBuildInputEvidence `
        $currentBackendManifest `
        $currentManagerManifest `
        $currentPostgresProvenance `
        $currentShawlProvenance `
        $currentVisualCppRuntimeProvenance
    $currentIsccProvenance = Get-TicketboxIsccProvenance $iscc
    $currentIsccProvenance | Add-Member `
        -NotePropertyName version_policy `
        -NotePropertyValue (Assert-TicketboxVendorVersionAllowed `
            $releaseConfig `
            "iscc" `
            $currentIsccProvenance.engine_version)
    Assert-TicketboxInstallerBuildProvenance $BackendRoot $installerBuild.Path $currentIsccProvenance $currentBuildInputs $defines | Out-Null

    $installerHash = Get-TicketboxFileSha256 $stagedInstaller
    $publishInstaller = Join-Path $publishStagingDir $installerFileName
    $publishChecksum = "$publishInstaller.sha256"
    $publishManifest = Join-Path $publishStagingDir "BUILD_PROVENANCE.json"
    $publishCompletion = Join-Path $publishStagingDir "BUILD_COMPLETE.json"
    Copy-Item -LiteralPath $stagedInstaller -Destination $publishInstaller
    Copy-Item -LiteralPath $stagedInstallerManifest -Destination $publishManifest
    $checksumText = "$installerHash  $installerFileName" + [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        $publishChecksum,
        $checksumText,
        (New-Object System.Text.UTF8Encoding($false))
    )
    if ((Get-TicketboxFileSha256 $publishInstaller) -cne $installerHash) {
        throw "发布 staging 安装包 hash 与 ISCC 输出不一致。"
    }
    $completion = [ordered]@{
        schema = "ticketbox-installer-publish-v1"
        version = $resolvedVersion
        installer = $installerFileName
        installer_sha256 = $installerHash
        checksum = "$installerFileName.sha256"
        provenance = "BUILD_PROVENANCE.json"
        provenance_sha256 = Get-TicketboxFileSha256 $publishManifest
    }
    Write-TicketboxJsonFile $publishCompletion $completion
    Assert-TicketboxInstallerPublishUnit `
        -PublishDirectory $publishStagingDir `
        -ExpectedVersion $resolvedVersion `
        -ExpectedCompilerProvenance $isccProvenance `
        -ExpectedBuildInputs $buildInputs `
        -ExpectedCompilerDefines $defines `
        -ExpectedInstallerSha256 $installerHash | Out-Null
    Publish-TicketboxInstallerUnit `
        -StagingDirectory $publishStagingDir `
        -TargetDirectory $targetPublishDir `
        -BackupDirectory $publishBackupDir `
        -PublishRoot $publishRoot `
        -ExpectedVersion $resolvedVersion `
        -ExpectedCompilerProvenance $isccProvenance `
        -ExpectedBuildInputs $buildInputs `
        -ExpectedCompilerDefines $defines `
        -ExpectedInstallerSha256 $installerHash `
        -ExpectedDirectoryName $publishUnitName
    Remove-TicketboxPublishFilesVerified `
        @($legacyInstaller, $legacyChecksum) `
        $publishRoot
    Remove-TicketboxPublishFilesVerified @($InstallerBuildManifest) $BackendRoot
}
catch {
    $BuildBodyFailure = $_
}
finally {
    foreach ($cleanup in @(
        [pscustomobject]@{ Label = "ISCC read locks"; Action = { Exit-TicketboxFileSetReadLocks $isccLocks } },
        [pscustomobject]@{ Label = "installer input read locks"; Action = { Exit-TicketboxFileSetReadLocks $inputLocks } },
        [pscustomobject]@{ Label = "installer publish staging"; Action = {
            if (Test-Path -LiteralPath $publishStagingDir) {
                Remove-TicketboxPublishDirectoryVerified $publishStagingDir $publishRoot
            }
        } },
        [pscustomobject]@{ Label = "installer build staging"; Action = {
            if (Test-Path -LiteralPath $buildStagingRoot) {
                Remove-TicketboxPublishDirectoryVerified $buildStagingRoot (Join-Path $BackendRoot "dist")
            }
        } }
    )) {
        try { & $cleanup.Action }
        catch { $InstallerCleanupFailures.Add("$($cleanup.Label): $($_.Exception.Message)") }
    }
}
if ($null -ne $BuildBodyFailure) { throw $BuildBodyFailure }
if ($InstallerHashOutputFile.Trim().Length -gt 0) {
    Write-TicketboxInstallerHashOutput `
        -Path $InstallerHashOutputFile `
        -InstallerSha256 $installerHash `
        -PublishRoot $publishRoot
}
Write-Ok "安装包发布单元：$targetPublishDir"
}
catch {
    $InstallerPrimaryFailure = $_
}
finally {
    try { Exit-TicketboxWindowsBuildLock $BuildLock }
    catch {
        $InstallerCleanupFailures.Add("Windows build lock: $($_.Exception.Message)")
        if ($null -eq $InstallerPrimaryFailure) {
            throw "Installer cleanup failed: $($InstallerCleanupFailures -join '; ')"
        }
    }
}
if ($null -ne $InstallerPrimaryFailure) {
    if ($InstallerCleanupFailures.Count -gt 0) {
        Write-Warning "Installer cleanup also failed after the primary error: $($InstallerCleanupFailures -join '; ')"
    }
    throw $InstallerPrimaryFailure
}
if ($InstallerCleanupFailures.Count -gt 0) {
    throw "Installer cleanup failed after publication: $($InstallerCleanupFailures -join '; ')"
}
