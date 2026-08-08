#Requires -Version 5.1

<#
.SYNOPSIS
  Shared database safety helpers for the bundled Ticketbox Windows installer.
.DESCRIPTION
  Validates loopback libpq targets, keeps credentials out of process argv, and
  verifies that backup commands are connected to the expected PostgreSQL data root.
#>

function ConvertTo-TicketboxLibpqUrl([string]$DatabaseUrl) {
    return $DatabaseUrl -replace '^postgresql\+\w+://', 'postgresql://'
}

function ConvertTo-TicketboxRequiredDatabaseUrl([string]$DatabaseUrl) {
    $driverMatch = [regex]::Match($DatabaseUrl, '^postgresql(?<driver>\+\w+)?://')
    if (-not $driverMatch.Success) {
        throw "DATABASE_URL 不是有效 PostgreSQL URL，拒绝继续。"
    }
    $libpqUrl = ConvertTo-TicketboxLibpqUrl $DatabaseUrl
    try {
        $builder = New-Object System.UriBuilder($libpqUrl)
    }
    catch {
        throw "DATABASE_URL 不是有效 PostgreSQL URL，拒绝继续。"
    }
    if (-not [string]::IsNullOrEmpty($builder.Fragment)) {
        throw "DATABASE_URL 不得包含 fragment。"
    }
    $query = $builder.Query.TrimStart('?')
    if (
        -not [string]::IsNullOrEmpty($query) -and
        $query -cne 'require_auth=scram-sha-256'
    ) {
        throw "DATABASE_URL query 必须只包含 require_auth=scram-sha-256。"
    }
    $builder.Query = 'require_auth=scram-sha-256'
    $hardened = $builder.Uri.AbsoluteUri
    if (-not [string]::IsNullOrEmpty($driverMatch.Groups['driver'].Value)) {
        $hardened = $hardened -replace '^postgresql://', (
            'postgresql' + $driverMatch.Groups['driver'].Value + '://'
        )
    }
    return $hardened
}

function Assert-TicketboxLocalDatabaseUrl([string]$DatabaseUrl, [int]$PgPort) {
    $libpqUrl = ConvertTo-TicketboxLibpqUrl (
        ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    )
    try {
        $uri = [System.Uri]$libpqUrl
    }
    catch {
        throw "DATABASE_URL 不是有效 PostgreSQL URL，拒绝继续。"
    }
    $address = $null
    $isLoopbackIp =
        [System.Net.IPAddress]::TryParse($uri.Host, [ref]$address) -and
        [System.Net.IPAddress]::IsLoopback($address)
    if ($uri.Scheme -ne "postgresql" -or -not $isLoopbackIp -or $uri.Port -ne $PgPort) {
        throw "DATABASE_URL 必须指向本机 PostgreSQL 端口 $PgPort，拒绝操作其它数据库。"
    }
    return $libpqUrl
}

function Get-TicketboxLocalDatabaseConnection {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][int]$PgPort,
        [Parameter(Mandatory = $true)][string]$ExpectedDatabase,
        [Parameter(Mandatory = $true)][string]$ExpectedRole
    )

    $persistedDatabaseUrl = ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    $libpqUrl = Assert-TicketboxLocalDatabaseUrl `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort
    $builder = New-Object System.UriBuilder($libpqUrl)
    $role = [System.Uri]::UnescapeDataString($builder.UserName)
    $database = [System.Uri]::UnescapeDataString($builder.Path.TrimStart("/"))
    if (-not [string]::Equals($role, $ExpectedRole, [System.StringComparison]::Ordinal)) {
        throw "DATABASE_URL 的 PostgreSQL 角色为 $role，预期为 $ExpectedRole。"
    }
    if (-not [string]::Equals($database, $ExpectedDatabase, [System.StringComparison]::Ordinal)) {
        throw "DATABASE_URL 的数据库为 $database，预期为 $ExpectedDatabase。"
    }
    $password = [System.Uri]::UnescapeDataString($builder.Password)
    if ([string]::IsNullOrWhiteSpace($password)) {
        throw "DATABASE_URL 必须包含非空 PostgreSQL 应用角色口令。"
    }
    $builder.Password = ""
    return [pscustomobject]@{
        DatabaseUrl = $builder.Uri.AbsoluteUri
        PersistedDatabaseUrl = $persistedDatabaseUrl
        Password = $password
    }
}

function Resolve-TicketboxPostgresServiceHostAuthority {
    <#
    .SYNOPSIS
      Derives the live bundled PostgreSQL host only from the exact SCM contract.
    .DESCRIPTION
      A current service may use either the legacy direct PGDATA path or the
      installer-owned runtime DataRoot projection. Arbitrary reparse points are
      never accepted: the runtime form is authorized only after the protected
      binding root, exact Volume-GUID junction target, DataRoot marker, ACLs,
      and both service SIDs have been revalidated by the shared installation
      safety boundary.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$ExpectedPgCtlPath,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    try {
        $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
        $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
        $canonicalPgCtl = ConvertTo-TicketboxWin32CanonicalPath $ExpectedPgCtlPath
        if (-not (Test-TicketboxPathWithin $canonicalPgCtl $canonicalInstallDir)) {
            throw "PostgreSQL pg_ctl.exe 不在当前安装目录内。"
        }
        if (-not (Test-TicketboxServiceExists $ServiceName)) {
            throw "受管 PostgreSQL 服务不存在：$ServiceName"
        }
        Assert-TicketboxServiceAccount `
            -Name $ServiceName `
            -ExpectedAccount "NT SERVICE\$ServiceName"

        $imagePath = Get-TicketboxServiceImagePath $ServiceName
        $arguments = @(Split-TicketboxWindowsCommandLine $imagePath)
        if (
            $arguments.Count -ne 7 -or
            $arguments[1] -cne "runservice" -or
            $arguments[2] -cne "-N" -or
            $arguments[3] -cne $ServiceName -or
            $arguments[4] -cne "-D" -or
            $arguments[6] -cne "-w"
        ) {
            throw "PostgreSQL SCM ImagePath 不符合受管宿主合同。"
        }
        $actualPgCtl = ConvertTo-TicketboxWin32CanonicalPath $arguments[0]
        $pgData = ConvertTo-TicketboxWin32CanonicalPath $arguments[5]
        if (-not (Test-TicketboxPathEquals $actualPgCtl $canonicalPgCtl)) {
            throw "PostgreSQL SCM executable 与当前安装目录不一致。"
        }
        if ((Get-TicketboxPathEntryKindNoFollow $canonicalPgCtl) -cne "File") {
            throw "PostgreSQL SCM executable 不是受保护普通文件。"
        }
        Assert-NoTicketboxAncestorReparsePoints $canonicalPgCtl
        Assert-TicketboxPgServiceCommand `
            -Name $ServiceName `
            -ExpectedExecutable $canonicalPgCtl `
            -ExpectedServiceName $ServiceName `
            -ExpectedDataRoot $pgData

        $physicalPgData = Join-Path $canonicalDataRoot "pgdata"
        $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath
        $expectedRuntimePgData = Join-Path $runtimeDataRoot "pgdata"
        $runtimeBinding = $null
        $usesRuntimeBinding = $false
        if (Test-TicketboxPathEquals $pgData $physicalPgData) {
            Assert-NoTicketboxAncestorReparsePoints $pgData
        }
        elseif (Test-TicketboxPathEquals $pgData $expectedRuntimePgData) {
            $usesRuntimeBinding = $true
            $serviceReadAccounts = @(
                (Get-TicketboxServiceSid $ServiceName),
                (Get-TicketboxServiceSid $BackendServiceName)
            )
            $runtimeBinding = Read-TicketboxRuntimeDataBinding `
                -DataRoot $canonicalDataRoot `
                -InstallDir $canonicalInstallDir `
                -ServiceReadExecuteAccounts $serviceReadAccounts `
                -DataRootMarkerAclPhase backend_read_optional `
                -ExpectedBackendServiceName $BackendServiceName
            if (-not (Test-TicketboxPathEquals `
                $pgData `
                $runtimeBinding.RuntimePgData)) {
                throw "PostgreSQL SCM PGDATA 与已验证 runtime binding 不一致。"
            }
        }
        else {
            throw "PostgreSQL SCM PGDATA 不匹配物理 DataRoot 或受管 runtime binding。"
        }
        if ((Get-TicketboxPathEntryKindNoFollow $pgData) -cne "Directory") {
            throw "PostgreSQL SCM 声明的 PGDATA 不是受管普通目录。"
        }

        $postmasterPidPath = Join-Path $pgData "postmaster.pid"
        if ((Get-TicketboxPathEntryKindNoFollow $postmasterPidPath) -cne "File") {
            throw "PostgreSQL 缺少受管 postmaster.pid。"
        }
        $pidLines = @(Get-Content -LiteralPath $postmasterPidPath -Encoding ASCII)
        if ($pidLines.Count -lt 4) {
            throw "PostgreSQL postmaster.pid 结构不完整。"
        }
        $postmasterPid = 0
        $port = 0
        if (
            -not [int]::TryParse($pidLines[0].Trim(), [ref]$postmasterPid) -or
            $postmasterPid -le 0 -or
            -not [int]::TryParse($pidLines[3].Trim(), [ref]$port) -or
            $port -lt 1 -or
            $port -gt 65535
        ) {
            throw "PostgreSQL postmaster.pid 的 PID/port 无效。"
        }
        $declaredDataRoot = $pidLines[1].Trim()
        $dataRootMatches = Test-TicketboxPathEquals $declaredDataRoot $pgData
        if ($usesRuntimeBinding -and -not $dataRootMatches) {
            # PostgreSQL may persist either the stable path supplied through
            # pg_ctl or its already-verified physical target. No third shape is
            # accepted.
            $dataRootMatches = Test-TicketboxPathEquals `
                $declaredDataRoot `
                $physicalPgData
        }
        if (-not $dataRootMatches) {
            throw "PostgreSQL postmaster.pid 的 data directory 与 SCM 不一致。"
        }
        $servicePid = Get-TicketboxServiceProcessId $ServiceName
        if ($servicePid -le 0) {
            throw "PostgreSQL SCM 服务没有有效宿主 PID。"
        }

        $psql = Join-Path (Split-Path -Parent $canonicalPgCtl) "psql.exe"
        if ((Get-TicketboxPathEntryKindNoFollow $psql) -cne "File") {
            throw "受管 PostgreSQL psql.exe 不存在。"
        }
        Assert-NoTicketboxAncestorReparsePoints $psql
        if ($usesRuntimeBinding) {
            $verifiedAgain = Read-TicketboxRuntimeDataBinding `
                -DataRoot $canonicalDataRoot `
                -InstallDir $canonicalInstallDir `
                -ServiceReadExecuteAccounts $serviceReadAccounts `
                -DataRootMarkerAclPhase backend_read_optional `
                -ExpectedBackendServiceName $BackendServiceName
            if (
                -not (Test-TicketboxPathEquals `
                    $verifiedAgain.RuntimePgData `
                    $runtimeBinding.RuntimePgData) -or
                [string]$verifiedAgain.DataVolumeIdentity -cne
                    [string]$runtimeBinding.DataVolumeIdentity -or
                [string]$verifiedAgain.VolumeBoundTarget -cne
                    [string]$runtimeBinding.VolumeBoundTarget
            ) {
                throw "PostgreSQL runtime binding 在宿主权威读取期间发生漂移。"
            }
        }
        return [pscustomobject][ordered]@{
            Schema = "ticketbox-windows-postgres-host-authority-v1"
            ServiceName = $ServiceName
            ServiceProcessId = $servicePid
            PostmasterProcessId = $postmasterPid
            PgCtlPath = $canonicalPgCtl
            PsqlPath = $psql
            PgData = $pgData
            PhysicalPgData = $physicalPgData
            Port = $port
            UsesRuntimeBinding = $usesRuntimeBinding
            DataVolumeIdentity = $(if ($usesRuntimeBinding) {
                [string]$runtimeBinding.DataVolumeIdentity
            } else { "" })
        }
    }
    catch {
        if ($_.Exception.Data.Contains("TicketboxInstallPublicFailureCode")) {
            throw
        }
        $failure = [InvalidOperationException]::new(
            "PostgreSQL SCM 宿主权威校验失败：$($_.Exception.Message)",
            $_.Exception
        )
        $failure.Data["TicketboxInstallPublicFailureCode"] =
            "postgres_host_authority_validation_failed"
        throw $failure
    }
}

function ConvertTo-TicketboxPgPassField([string]$Value) {
    if ($Value.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw "PostgreSQL 连接字段不能写入 passfile。"
    }
    return $Value.Replace("\", "\\").Replace(":", "\:")
}

function ConvertTo-TicketboxNativeCommandLineArgument([string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
        }
        else {
            [void]$builder.Append(('\' * $backslashes))
            [void]$builder.Append($character)
        }
        $backslashes = 0
    }
    [void]$builder.Append(('\' * ($backslashes * 2)))
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Initialize-TicketboxBoundedNativeProcessMethods {
    if ("TicketboxBoundedNativeProcess" -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

public sealed class TicketboxProcessTreeTerminationException : Exception
{
    public const string StableFailureCode = "tree_termination_unconfirmed";

    public string FailureCode { get; private set; }

    public TicketboxProcessTreeTerminationException(string detail)
        : this(detail, null)
    {
    }

    public TicketboxProcessTreeTerminationException(
        string detail,
        Exception innerException)
        : base(StableFailureCode + ": " + detail, innerException)
    {
        FailureCode = StableFailureCode;
        Data["TicketboxC07FailureCode"] = StableFailureCode;
    }
}

public sealed class TicketboxProcessTreeTerminationAggregateException
    : AggregateException
{
    public string FailureCode { get; private set; }

    public TicketboxProcessTreeTerminationAggregateException(
        string message,
        Exception[] failures)
        : base(message, failures)
    {
        FailureCode =
            TicketboxProcessTreeTerminationException.StableFailureCode;
        Data["TicketboxC07FailureCode"] = FailureCode;
        Data["TicketboxC07FailureCodes"] = FailureCode;
    }
}

public sealed class TicketboxC07HeartbeatHelperException : Exception
{
    public string FailureCode { get; private set; }

    public TicketboxC07HeartbeatHelperException(
        string failureCode,
        string detail)
        : this(failureCode, detail, null)
    {
    }

    public TicketboxC07HeartbeatHelperException(
        string failureCode,
        string detail,
        Exception innerException)
        : base(failureCode + ": " + detail, innerException)
    {
        if (String.IsNullOrWhiteSpace(failureCode))
        {
            throw new ArgumentException("Heartbeat failure code is required.");
        }
        FailureCode = failureCode;
        Data["TicketboxC07FailureCode"] = failureCode;
    }
}

public sealed class TicketboxC07DurableHeartbeatOperation
{
    public const string OperationSchema =
        "ticketbox-c07-durable-heartbeat-operation-v2";

    public string Schema { get { return OperationSchema; } }
    public string DataRoot { get; private set; }
    public object LifecycleLock { get; private set; }
    public string OperationId { get; private set; }
    public string DescriptorSha256 { get; private set; }
    public string CoordinatorBindingSha256 { get; private set; }
    public long CoordinatorBindingSequence { get; private set; }
    public string MaintenanceAttemptId { get; private set; }
    public string MaintenanceAttemptSha256 { get; private set; }
    public long MaintenanceAttemptSequence { get; private set; }
    public int CoordinatorProcessId { get; private set; }
    public uint CoordinatorStartedFileTimeHigh { get; private set; }
    public uint CoordinatorStartedFileTimeLow { get; private set; }
    public DateTime DeadlineUtc { get; private set; }
    public long RemainingCeilingAtCaptureMilliseconds { get; private set; }
    public long CapturedStopwatchTimestamp { get; private set; }
    private readonly string[] hostFullControlAccounts;
    private readonly string[] installationIdentityAclAccounts;

    public string[] HostFullControlAccounts
    {
        get { return (string[])hostFullControlAccounts.Clone(); }
    }
    public string HostOwnerAccount { get; private set; }
    public string[] InstallationIdentityAclAccounts
    {
        get { return (string[])installationIdentityAclAccounts.Clone(); }
    }
    public string InstallationIdentityOwnerAccount { get; private set; }
    public string PrimaryLifecycleLockPath { get; private set; }
    public string OperationLifecycleLockPath { get; private set; }

    public TicketboxC07DurableHeartbeatOperation(
        string dataRoot,
        object lifecycleLock,
        string operationId,
        string descriptorSha256,
        string coordinatorBindingSha256,
        long coordinatorBindingSequence,
        string maintenanceAttemptId,
        string maintenanceAttemptSha256,
        long maintenanceAttemptSequence,
        int coordinatorProcessId,
        uint coordinatorStartedFileTimeHigh,
        uint coordinatorStartedFileTimeLow,
        DateTime deadlineUtc,
        long remainingCeilingMilliseconds,
        string[] hostFullControlAccounts,
        string hostOwnerAccount,
        string[] installationIdentityAclAccounts,
        string installationIdentityOwnerAccount,
        string primaryLifecycleLockPath,
        string operationLifecycleLockPath)
    {
        if (String.IsNullOrWhiteSpace(dataRoot) || lifecycleLock == null ||
            String.IsNullOrWhiteSpace(operationId) ||
            String.IsNullOrWhiteSpace(descriptorSha256) ||
            String.IsNullOrWhiteSpace(coordinatorBindingSha256) ||
            coordinatorBindingSequence < 0 ||
            String.IsNullOrWhiteSpace(maintenanceAttemptId) ||
            String.IsNullOrWhiteSpace(maintenanceAttemptSha256) ||
            maintenanceAttemptSequence < 1 || coordinatorProcessId <= 0 ||
            deadlineUtc.Kind != DateTimeKind.Utc ||
            remainingCeilingMilliseconds < 1 ||
            remainingCeilingMilliseconds > 1200000 ||
            hostFullControlAccounts == null ||
            hostFullControlAccounts.Length == 0 ||
            String.IsNullOrWhiteSpace(hostOwnerAccount) ||
            installationIdentityAclAccounts == null ||
            installationIdentityAclAccounts.Length == 0 ||
            String.IsNullOrWhiteSpace(installationIdentityOwnerAccount) ||
            String.IsNullOrWhiteSpace(primaryLifecycleLockPath) ||
            String.IsNullOrWhiteSpace(operationLifecycleLockPath))
        {
            throw new ArgumentException(
                "C07 durable heartbeat operation is incomplete.");
        }
        DataRoot = dataRoot;
        LifecycleLock = lifecycleLock;
        OperationId = operationId;
        DescriptorSha256 = descriptorSha256;
        CoordinatorBindingSha256 = coordinatorBindingSha256;
        CoordinatorBindingSequence = coordinatorBindingSequence;
        MaintenanceAttemptId = maintenanceAttemptId;
        MaintenanceAttemptSha256 = maintenanceAttemptSha256;
        MaintenanceAttemptSequence = maintenanceAttemptSequence;
        CoordinatorProcessId = coordinatorProcessId;
        CoordinatorStartedFileTimeHigh = coordinatorStartedFileTimeHigh;
        CoordinatorStartedFileTimeLow = coordinatorStartedFileTimeLow;
        DeadlineUtc = deadlineUtc;
        RemainingCeilingAtCaptureMilliseconds =
            remainingCeilingMilliseconds;
        CapturedStopwatchTimestamp = Stopwatch.GetTimestamp();
        this.hostFullControlAccounts =
            (string[])hostFullControlAccounts.Clone();
        HostOwnerAccount = hostOwnerAccount;
        this.installationIdentityAclAccounts =
            (string[])installationIdentityAclAccounts.Clone();
        InstallationIdentityOwnerAccount = installationIdentityOwnerAccount;
        PrimaryLifecycleLockPath = primaryLifecycleLockPath;
        OperationLifecycleLockPath = operationLifecycleLockPath;
    }

    public long GetRemainingCeilingMilliseconds()
    {
        long elapsedTicks =
            Stopwatch.GetTimestamp() - CapturedStopwatchTimestamp;
        double elapsedMilliseconds =
            ((double)elapsedTicks * 1000.0) / (double)Stopwatch.Frequency;
        double monotonicRemaining =
            (double)RemainingCeilingAtCaptureMilliseconds -
            elapsedMilliseconds;
        double wallRemaining =
            (DeadlineUtc - DateTime.UtcNow).TotalMilliseconds;
        double remaining = Math.Min(monotonicRemaining, wallRemaining);
        if (remaining <= 0.0)
        {
            return 0;
        }
        return checked((long)Math.Floor(remaining));
    }
}

public sealed class TicketboxBoundedNativeProcess : IDisposable
{
    private const uint CreateSuspended = 0x00000004;
    private const uint CreateUnicodeEnvironment = 0x00000400;
    private const uint ExtendedStartupInfoPresent = 0x00080000;
    private const uint CreateNoWindow = 0x08000000;
    private const uint StartfUseStdHandles = 0x00000100;
    private const uint HandleFlagInherit = 0x00000001;
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private const int JobObjectBasicAccountingInformation = 1;
    private const int JobObjectExtendedLimitInformation = 9;
    private const int ProcThreadAttributeHandleList = 0x00020002;
    private const uint WaitObject0 = 0x00000000;
    private const uint WaitTimeout = 0x00000102;
    private const uint WaitFailed = 0xFFFFFFFF;
    private const uint ResumeFailed = 0xFFFFFFFF;

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public int Length;
        public IntPtr SecurityDescriptor;
        public int InheritHandle;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int Size;
        public string Reserved;
        public string Desktop;
        public string Title;
        public int X;
        public int Y;
        public int XSize;
        public int YSize;
        public int XCountChars;
        public int YCountChars;
        public int FillAttribute;
        public int Flags;
        public short ShowWindow;
        public short Reserved2Size;
        public IntPtr Reserved2;
        public IntPtr StandardInput;
        public IntPtr StandardOutput;
        public IntPtr StandardError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct STARTUPINFOEX
    {
        public STARTUPINFO StartupInfo;
        public IntPtr AttributeList;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr Process;
        public IntPtr Thread;
        public uint ProcessId;
        public uint ThreadId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
    {
        public long TotalUserTime;
        public long TotalKernelTime;
        public long ThisPeriodTotalUserTime;
        public long ThisPeriodTotalKernelTime;
        public uint TotalPageFaultCount;
        public uint TotalProcesses;
        public uint ActiveProcesses;
        public uint TotalTerminatedProcesses;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeWaitHandle CreateJobObject(
        IntPtr jobAttributes,
        string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        SafeWaitHandle job,
        int informationClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryInformationJobObject(
        SafeWaitHandle job,
        int informationClass,
        out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information,
        uint informationLength,
        IntPtr returnLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(
        SafeWaitHandle job,
        uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(
        SafeWaitHandle job,
        SafeWaitHandle process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(
        out SafeFileHandle readPipe,
        out SafeFileHandle writePipe,
        ref SECURITY_ATTRIBUTES pipeAttributes,
        uint size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetHandleInformation(
        SafeFileHandle handle,
        uint mask,
        uint flags);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(
        IntPtr attributeList,
        int attributeCount,
        uint flags,
        ref IntPtr size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(
        IntPtr attributeList,
        uint flags,
        IntPtr attribute,
        IntPtr value,
        IntPtr size,
        IntPtr previousValue,
        IntPtr returnSize);

    [DllImport("kernel32.dll")]
    private static extern void DeleteProcThreadAttributeList(
        IntPtr attributeList);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessW(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFOEX startupInfo,
        out PROCESS_INFORMATION processInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(SafeWaitHandle thread);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(
        SafeWaitHandle process,
        uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(
        SafeWaitHandle handle,
        uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(
        SafeWaitHandle process,
        out uint exitCode);

    private SafeWaitHandle job;
    private SafeWaitHandle process;
    private FileStream standardInputStream;
    private FileStream standardOutputStream;
    private FileStream standardErrorStream;
    private bool disposed;

    public StreamWriter StandardInput { get; private set; }
    public StreamReader StandardOutput { get; private set; }
    public StreamReader StandardError { get; private set; }
    public uint ProcessId { get; private set; }

    private TicketboxBoundedNativeProcess()
    {
    }

    private static Win32Exception NativeFailure(string operation)
    {
        return new Win32Exception(
            Marshal.GetLastWin32Error(),
            operation + " failed");
    }

    private static bool IsProcessSignaled(SafeWaitHandle processHandle)
    {
        uint result = WaitForSingleObject(processHandle, 0);
        if (result == WaitObject0)
        {
            return true;
        }
        if (result == WaitTimeout)
        {
            return false;
        }
        if (result == WaitFailed)
        {
            throw NativeFailure("WaitForSingleObject");
        }
        throw new InvalidOperationException(
            "WaitForSingleObject returned an unexpected status.");
    }

    private static uint ReadActiveProcessCount(SafeWaitHandle jobHandle)
    {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information;
        if (!QueryInformationJobObject(
            jobHandle,
            JobObjectBasicAccountingInformation,
            out information,
            checked((uint)Marshal.SizeOf(
                typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION))),
            IntPtr.Zero))
        {
            throw NativeFailure("QueryInformationJobObject");
        }
        return information.ActiveProcesses;
    }

    private static void WaitForTreeSettlement(
        SafeWaitHandle jobHandle,
        SafeWaitHandle processHandle,
        int settlementMilliseconds,
        Exception terminationFailure)
    {
        if (settlementMilliseconds < 1)
        {
            throw new ArgumentOutOfRangeException("settlementMilliseconds");
        }
        Stopwatch settlement = Stopwatch.StartNew();
        bool rootSignaled = false;
        uint activeProcesses = UInt32.MaxValue;
        Exception probeFailure = null;
        while (true)
        {
            try
            {
                rootSignaled = IsProcessSignaled(processHandle);
                activeProcesses = ReadActiveProcessCount(jobHandle);
                probeFailure = null;
                if (rootSignaled && activeProcesses == 0)
                {
                    return;
                }
            }
            catch (Exception failure)
            {
                probeFailure = failure;
            }

            long remaining =
                (long)settlementMilliseconds - settlement.ElapsedMilliseconds;
            if (remaining <= 0)
            {
                break;
            }
            int waitMilliseconds = checked((int)Math.Min(remaining, 20L));
            if (!rootSignaled)
            {
                uint waitResult = WaitForSingleObject(
                    processHandle,
                    checked((uint)waitMilliseconds));
                if (waitResult == WaitFailed)
                {
                    probeFailure = NativeFailure("WaitForSingleObject");
                }
                else if (waitResult != WaitObject0 && waitResult != WaitTimeout)
                {
                    probeFailure = new InvalidOperationException(
                        "WaitForSingleObject returned an unexpected status.");
                }
            }
            else
            {
                Thread.Sleep(waitMilliseconds);
            }
        }

        Exception innerFailure = probeFailure ?? terminationFailure;
        string detail =
            "termination settlement exceeded " +
            settlementMilliseconds.ToString() +
            " ms (root_signaled=" + rootSignaled.ToString() +
            ", active_processes=" + activeProcesses.ToString() + ").";
        throw new TicketboxProcessTreeTerminationException(
            detail,
            innerFailure);
    }

    private static void TerminateCreatedProcessAndConfirm(
        SafeWaitHandle jobHandle,
        SafeWaitHandle processHandle,
        bool assignedToJob,
        int settlementMilliseconds)
    {
        Exception terminationFailure = null;
        if (assignedToJob && jobHandle != null && !jobHandle.IsInvalid)
        {
            if (!TerminateJobObject(jobHandle, 1))
            {
                terminationFailure = NativeFailure("TerminateJobObject");
            }
            WaitForTreeSettlement(
                jobHandle,
                processHandle,
                settlementMilliseconds,
                terminationFailure);
            return;
        }

        if (!TerminateProcess(processHandle, 1))
        {
            terminationFailure = NativeFailure("TerminateProcess");
        }
        Stopwatch settlement = Stopwatch.StartNew();
        while (true)
        {
            try
            {
                if (IsProcessSignaled(processHandle))
                {
                    return;
                }
            }
            catch (Exception failure)
            {
                terminationFailure = failure;
            }
            long remaining =
                (long)settlementMilliseconds - settlement.ElapsedMilliseconds;
            if (remaining <= 0)
            {
                throw new TicketboxProcessTreeTerminationException(
                    "unassigned suspended process did not signal within " +
                    settlementMilliseconds.ToString() + " ms.",
                    terminationFailure);
            }
            uint waitResult = WaitForSingleObject(
                processHandle,
                checked((uint)Math.Min(remaining, 20L)));
            if (waitResult == WaitFailed)
            {
                terminationFailure = NativeFailure("WaitForSingleObject");
            }
        }
    }

    private static TicketboxProcessTreeTerminationAggregateException
        NewTerminationAggregate(
        string message,
        Exception operationFailure,
        Exception settlementFailure)
    {
        return new TicketboxProcessTreeTerminationAggregateException(
            message,
            new Exception[] { operationFailure, settlementFailure });
    }

    private static Encoding GetStrictConsoleInputEncoding()
    {
        // Redirected stdin is a byte protocol, not an attached console. Use
        // one explicit no-BOM encoding so PowerShell 5.1, PowerShell 7, psql,
        // and helper processes observe the same first byte and fail closed on
        // invalid UTF-16 input rather than inheriting a mutable code page.
        return new UTF8Encoding(false, true);
    }

    private static void CloseFileHandle(ref SafeFileHandle handle)
    {
        if (handle != null)
        {
            handle.Dispose();
            handle = null;
        }
    }

    private static void CloseWaitHandle(ref SafeWaitHandle handle)
    {
        if (handle != null)
        {
            handle.Dispose();
            handle = null;
        }
    }

    private static void MakeParentPipeEndNonInheritable(
        SafeFileHandle handle,
        string label)
    {
        if (!SetHandleInformation(handle, HandleFlagInherit, 0))
        {
            throw NativeFailure(label + " SetHandleInformation");
        }
    }

    private static IntPtr BuildEnvironmentBlock(IDictionary environmentVariables)
    {
        if (environmentVariables == null)
        {
            return IntPtr.Zero;
        }
        SortedDictionary<string, string> sorted =
            new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry entry in environmentVariables)
        {
            string name = entry.Key as string;
            string value = entry.Value as string;
            if (String.IsNullOrEmpty(name) || value == null)
            {
                throw new ArgumentException(
                    "Child environment names and values must be strings.");
            }
            // Windows may expose hidden per-drive current-directory entries such
            // as '=C:'. They are not ordinary environment variables and are not
            // needed by the absolute-path C07 helper, so a copied environment
            // drops them instead of rejecting the entire child launch.
            if (name[0] == '=')
            {
                continue;
            }
            if (name.IndexOf('=') >= 0 || name.IndexOf('\0') >= 0 ||
                value.IndexOf('\0') >= 0)
            {
                throw new ArgumentException(
                    "Child environment contains an invalid name or value.");
            }
            if (sorted.ContainsKey(name))
            {
                throw new ArgumentException(
                    "Child environment contains a case-insensitive duplicate name.");
            }
            sorted.Add(name, value);
        }
        StringBuilder block = new StringBuilder();
        bool first = true;
        foreach (KeyValuePair<string, string> entry in sorted)
        {
            if (!first)
            {
                block.Append('\0');
            }
            block.Append(entry.Key);
            block.Append('=');
            block.Append(entry.Value);
            first = false;
        }
        // StringToHGlobalUni contributes the second trailing NUL. For an empty
        // environment this explicit NUL plus its terminator still forms \0\0.
        block.Append('\0');
        return Marshal.StringToHGlobalUni(block.ToString());
    }

    public static TicketboxBoundedNativeProcess Start(
        string applicationPath,
        string commandLine)
    {
        return Start(applicationPath, commandLine, null);
    }

    public static TicketboxBoundedNativeProcess Start(
        string applicationPath,
        string commandLine,
        IDictionary environmentVariables)
    {
        SafeWaitHandle jobHandle = null;
        SafeWaitHandle processHandle = null;
        SafeWaitHandle threadHandle = null;
        SafeFileHandle childInput = null;
        SafeFileHandle parentInput = null;
        SafeFileHandle parentOutput = null;
        SafeFileHandle childOutput = null;
        SafeFileHandle parentError = null;
        SafeFileHandle childError = null;
        IntPtr attributeList = IntPtr.Zero;
        IntPtr inheritedHandles = IntPtr.Zero;
        IntPtr environmentBlock = IntPtr.Zero;
        bool attributeListInitialized = false;
        bool assignedToJob = false;
        bool returned = false;
        TicketboxBoundedNativeProcess result = null;
        try
        {
            jobHandle = CreateJobObject(IntPtr.Zero, null);
            if (jobHandle == null || jobHandle.IsInvalid)
            {
                throw NativeFailure("CreateJobObject");
            }
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits =
                new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags =
                JobObjectLimitKillOnJobClose;
            if (!SetInformationJobObject(
                jobHandle,
                JobObjectExtendedLimitInformation,
                ref limits,
                checked((uint)Marshal.SizeOf(
                    typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)))))
            {
                throw NativeFailure("SetInformationJobObject");
            }

            SECURITY_ATTRIBUTES pipeAttributes = new SECURITY_ATTRIBUTES();
            pipeAttributes.Length = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES));
            pipeAttributes.InheritHandle = 1;
            if (!CreatePipe(
                out childInput,
                out parentInput,
                ref pipeAttributes,
                0))
            {
                throw NativeFailure("stdin CreatePipe");
            }
            MakeParentPipeEndNonInheritable(parentInput, "stdin parent");
            if (!CreatePipe(
                out parentOutput,
                out childOutput,
                ref pipeAttributes,
                0))
            {
                throw NativeFailure("stdout CreatePipe");
            }
            MakeParentPipeEndNonInheritable(parentOutput, "stdout parent");
            if (!CreatePipe(
                out parentError,
                out childError,
                ref pipeAttributes,
                0))
            {
                throw NativeFailure("stderr CreatePipe");
            }
            MakeParentPipeEndNonInheritable(parentError, "stderr parent");

            IntPtr attributeListSize = IntPtr.Zero;
            InitializeProcThreadAttributeList(
                IntPtr.Zero,
                1,
                0,
                ref attributeListSize);
            if (attributeListSize == IntPtr.Zero)
            {
                throw NativeFailure("InitializeProcThreadAttributeList size");
            }
            attributeList = Marshal.AllocHGlobal(attributeListSize);
            if (!InitializeProcThreadAttributeList(
                attributeList,
                1,
                0,
                ref attributeListSize))
            {
                throw NativeFailure("InitializeProcThreadAttributeList");
            }
            attributeListInitialized = true;
            inheritedHandles = Marshal.AllocHGlobal(checked(IntPtr.Size * 3));
            Marshal.WriteIntPtr(
                inheritedHandles,
                0,
                childInput.DangerousGetHandle());
            Marshal.WriteIntPtr(
                inheritedHandles,
                IntPtr.Size,
                childOutput.DangerousGetHandle());
            Marshal.WriteIntPtr(
                inheritedHandles,
                IntPtr.Size * 2,
                childError.DangerousGetHandle());
            if (!UpdateProcThreadAttribute(
                attributeList,
                0,
                new IntPtr(ProcThreadAttributeHandleList),
                inheritedHandles,
                new IntPtr(IntPtr.Size * 3),
                IntPtr.Zero,
                IntPtr.Zero))
            {
                throw NativeFailure("UpdateProcThreadAttribute handle list");
            }

            STARTUPINFOEX startupInfo = new STARTUPINFOEX();
            startupInfo.StartupInfo.Size = Marshal.SizeOf(typeof(STARTUPINFOEX));
            startupInfo.StartupInfo.Flags = checked((int)StartfUseStdHandles);
            startupInfo.StartupInfo.StandardInput = childInput.DangerousGetHandle();
            startupInfo.StartupInfo.StandardOutput = childOutput.DangerousGetHandle();
            startupInfo.StartupInfo.StandardError = childError.DangerousGetHandle();
            startupInfo.AttributeList = attributeList;
            PROCESS_INFORMATION processInformation;
            uint creationFlags =
                CreateSuspended |
                ExtendedStartupInfoPresent |
                CreateNoWindow;
            environmentBlock = BuildEnvironmentBlock(environmentVariables);
            if (environmentBlock != IntPtr.Zero)
            {
                creationFlags |= CreateUnicodeEnvironment;
            }
            if (!CreateProcessW(
                applicationPath,
                new StringBuilder(commandLine),
                IntPtr.Zero,
                IntPtr.Zero,
                true,
                creationFlags,
                environmentBlock,
                null,
                ref startupInfo,
                out processInformation))
            {
                throw NativeFailure("CreateProcessW");
            }
            processHandle = new SafeWaitHandle(
                processInformation.Process,
                true);
            threadHandle = new SafeWaitHandle(
                processInformation.Thread,
                true);

            // CreateProcess has duplicated the allowlisted standard handles.
            // Closing the parent copies is required for deterministic pipe EOF.
            CloseFileHandle(ref childInput);
            CloseFileHandle(ref childOutput);
            CloseFileHandle(ref childError);

            // The primary thread remains suspended here. If the current host job
            // cannot safely form a nested hierarchy, assignment fails before any
            // user instruction executes and the suspended process is terminated.
            if (!AssignProcessToJobObject(jobHandle, processHandle))
            {
                throw NativeFailure("AssignProcessToJobObject");
            }
            assignedToJob = true;
            if (ResumeThread(threadHandle) == ResumeFailed)
            {
                throw NativeFailure("ResumeThread");
            }
            CloseWaitHandle(ref threadHandle);

            result = new TicketboxBoundedNativeProcess();
            result.ProcessId = processInformation.ProcessId;
            result.standardInputStream = new FileStream(
                parentInput,
                FileAccess.Write,
                4096,
                false);
            parentInput = null;
            result.standardOutputStream = new FileStream(
                parentOutput,
                FileAccess.Read,
                4096,
                false);
            parentOutput = null;
            result.standardErrorStream = new FileStream(
                parentError,
                FileAccess.Read,
                4096,
                false);
            parentError = null;
            result.StandardInput = new StreamWriter(
                result.standardInputStream,
                GetStrictConsoleInputEncoding(),
                4096);
            result.StandardOutput = new StreamReader(
                result.standardOutputStream,
                Console.OutputEncoding,
                true,
                4096);
            result.StandardError = new StreamReader(
                result.standardErrorStream,
                Console.OutputEncoding,
                true,
                4096);
            result.job = jobHandle;
            jobHandle = null;
            result.process = processHandle;
            processHandle = null;
            returned = true;
            return result;
        }
        catch (Exception startFailure)
        {
            if (processHandle != null && !processHandle.IsInvalid)
            {
                try
                {
                    TerminateCreatedProcessAndConfirm(
                        jobHandle,
                        processHandle,
                        assignedToJob,
                        5000);
                }
                catch (Exception settlementFailure)
                {
                    throw NewTerminationAggregate(
                        "Native process launch failed and process-tree " +
                        "termination could not be confirmed.",
                        startFailure,
                        settlementFailure);
                }
            }
            if (result != null)
            {
                result.Dispose();
            }
            throw;
        }
        finally
        {
            if (attributeListInitialized)
            {
                DeleteProcThreadAttributeList(attributeList);
            }
            if (attributeList != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(attributeList);
            }
            if (inheritedHandles != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(inheritedHandles);
            }
            if (environmentBlock != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(environmentBlock);
            }
            CloseFileHandle(ref childInput);
            CloseFileHandle(ref childOutput);
            CloseFileHandle(ref childError);
            CloseWaitHandle(ref threadHandle);
            if (!returned)
            {
                CloseFileHandle(ref parentInput);
                CloseFileHandle(ref parentOutput);
                CloseFileHandle(ref parentError);
                CloseWaitHandle(ref processHandle);
                CloseWaitHandle(ref jobHandle);
            }
        }
    }

    private void AssertOpen()
    {
        if (disposed)
        {
            throw new ObjectDisposedException("TicketboxBoundedNativeProcess");
        }
    }

    public bool WaitForExit(int milliseconds)
    {
        AssertOpen();
        if (milliseconds < 0)
        {
            throw new ArgumentOutOfRangeException("milliseconds");
        }
        uint result = WaitForSingleObject(process, checked((uint)milliseconds));
        if (result == WaitObject0)
        {
            return true;
        }
        if (result == WaitTimeout)
        {
            return false;
        }
        if (result == WaitFailed)
        {
            throw NativeFailure("WaitForSingleObject");
        }
        throw new InvalidOperationException(
            "WaitForSingleObject returned an unexpected status.");
    }

    public uint GetActiveProcessCount()
    {
        AssertOpen();
        return ReadActiveProcessCount(job);
    }

    public int GetExitCode()
    {
        AssertOpen();
        uint exitCode;
        if (!GetExitCodeProcess(process, out exitCode))
        {
            throw NativeFailure("GetExitCodeProcess");
        }
        return unchecked((int)exitCode);
    }

    public void Terminate(int settlementMilliseconds)
    {
        AssertOpen();
        try
        {
            bool rootSignaled = IsProcessSignaled(process);
            uint activeProcesses = ReadActiveProcessCount(job);
            if (rootSignaled && activeProcesses == 0)
            {
                return;
            }
        }
        catch
        {
            // A failed pre-probe never authorizes returning. Issue termination
            // and let the bounded settlement loop produce the stable failure.
        }
        Exception terminationFailure = null;
        if (!TerminateJobObject(job, 1))
        {
            terminationFailure = NativeFailure("TerminateJobObject");
        }
        WaitForTreeSettlement(
            job,
            process,
            settlementMilliseconds,
            terminationFailure);
    }

    private static void CloseStream(IDisposable stream)
    {
        if (stream == null)
        {
            return;
        }
        try
        {
            stream.Dispose();
        }
        catch
        {
        }
    }

    public void Abort(int settlementMilliseconds)
    {
        try
        {
            Terminate(settlementMilliseconds);
        }
        finally
        {
            // Close the raw parent pipe ends without asking StreamWriter to
            // synchronously flush a write that may be blocked in the kernel.
            CloseStream(standardInputStream);
            CloseStream(standardOutputStream);
            CloseStream(standardErrorStream);
        }
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }
        disposed = true;
        // KILL_ON_JOB_CLOSE is the final fail-closed guard even if a caller
        // leaves through an unexpected exception before calling Abort().
        if (job != null)
        {
            job.Dispose();
            job = null;
        }
        CloseStream(standardInputStream);
        CloseStream(standardOutputStream);
        CloseStream(standardErrorStream);
        CloseStream(StandardInput);
        CloseStream(StandardOutput);
        CloseStream(StandardError);
        if (process != null)
        {
            process.Dispose();
            process = null;
        }
    }
}
'@
}

function New-TicketboxNativeProcessTerminationAggregate {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][Exception]$OperationFailure,
        [Parameter(Mandatory = $true)][Exception]$TerminationFailure
    )

    [Exception[]]$failures = @($OperationFailure, $TerminationFailure)
    $aggregate = [TicketboxProcessTreeTerminationAggregateException]::new(
        (
            "$Label 失败，且完整进程树的终止结算无法确认；" +
            "禁止继续数据库补偿。"
        ),
        $failures
    )
    return $aggregate
}

function Stop-TicketboxBoundedNativeProcessTree {
    param(
        [Parameter(Mandatory = $true)][object]$NativeProcess,
        [Parameter(Mandatory = $true)]
        [ValidateRange(100, 30000)][int]$SettlementMilliseconds
    )

    $NativeProcess.Abort($SettlementMilliseconds)
}

function Assert-TicketboxC07DurableHeartbeatOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (
        $Operation.GetType().FullName -cne
            "TicketboxC07DurableHeartbeatOperation" -or
        [string]$Operation.Schema -cne
            "ticketbox-c07-durable-heartbeat-operation-v2" -or
        [string]$Operation.MaintenanceAttemptId -cnotmatch
            "^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" -or
        [string]$Operation.MaintenanceAttemptSha256 -cnotmatch
            "^[0-9A-F]{64}$" -or
        [int64]$Operation.MaintenanceAttemptSequence -lt 1
    ) {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_operation_invalid",
            "$Label heartbeat operation 类型不受支持。"
        )
    }
    if (
        $null -eq (
            Get-Command `
                Assert-TicketboxC07LifecycleLease `
                -ErrorAction SilentlyContinue
        ) -or
        $null -eq (
            Get-Command `
                Get-TicketboxProcessIdentity `
                -ErrorAction SilentlyContinue
        )
    ) {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_operation_invalid",
            "$Label heartbeat operation 缺少 lifecycle lease verifier。"
        )
    }
    try {
        Assert-TicketboxC07LifecycleLease $Operation.LifecycleLock |
            Out-Null
        $currentCoordinator = Get-TicketboxProcessIdentity -ProcessId $PID
        if (
            [int]$currentCoordinator.ProcessId -ne
                [int]$Operation.CoordinatorProcessId -or
            [uint32]$currentCoordinator.StartedFileTimeHigh -ne
                [uint32]$Operation.CoordinatorStartedFileTimeHigh -or
            [uint32]$currentCoordinator.StartedFileTimeLow -ne
                [uint32]$Operation.CoordinatorStartedFileTimeLow
        ) {
            throw "$Label heartbeat operation coordinator identity 已漂移。"
        }
    }
    catch {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_lease_invalid",
            "$Label heartbeat operation 不再持有 coordinator lifecycle lease。",
            $_.Exception.GetBaseException()
        )
    }
}

function Get-TicketboxC07HeartbeatHelperScriptPath {
    $path = [IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "windows_c07_heartbeat_helper.ps1")
    )
    Assert-NoTicketboxAncestorReparsePoints $path
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_bootstrap_invalid",
            "C07 heartbeat helper 不是可信普通文件：$path"
        )
    }
    return $path
}

function Get-TicketboxC07HeartbeatHelperExecutablePath {
    try {
        $systemDirectory = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::System
        )
        if ([string]::IsNullOrWhiteSpace($systemDirectory)) {
            throw "Windows system directory 不可用。"
        }
        # The packaged PowerShell 7 native launcher can broker descendants
        # outside the caller's Job Object. C07 standardizes the settlement
        # carrier on the inbox 5.1 host required by these packaging scripts;
        # both 5.1 and 7 coordinators therefore get identical descendant
        # membership and KILL_ON_JOB_CLOSE behavior.
        $path = [IO.Path]::GetFullPath(
            (Join-Path `
                $systemDirectory `
                "WindowsPowerShell\v1.0\powershell.exe")
        )
    }
    catch {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_bootstrap_invalid",
            "无法解析 Windows PowerShell 5.1 helper executable。",
            $_.Exception.GetBaseException()
        )
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_bootstrap_invalid",
            "C07 heartbeat PowerShell executable 不是普通文件：$path"
        )
    }
    return $path
}

function New-TicketboxC07HeartbeatHelperChildEnvironment {
    # The helper consumes one descriptor over stdin and resolves every project
    # dependency by absolute path.  It must not inherit the coordinator's
    # ambient environment: deny-listing credential-shaped names inevitably
    # misses provider-specific variables such as GITHUB_PAT or
    # DOCKER_AUTH_CONFIG.  Build only the Windows/.NET substrate required by
    # the inbox PowerShell 5.1 helper and its Add-Type calls.
    $systemDirectory = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
    )
    $windowsDirectory = [IO.Path]::GetFullPath(
        (Split-Path -Parent $systemDirectory)
    )
    $helperExecutable = Get-TicketboxC07HeartbeatHelperExecutablePath
    $helperHome = Split-Path -Parent $helperExecutable
    $systemModulePath = [IO.Path]::GetFullPath(
        (Join-Path $helperHome "Modules")
    )
    $programFilesDirectory = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::ProgramFiles
        )
    )
    $sharedModulePath = [IO.Path]::GetFullPath(
        (Join-Path $programFilesDirectory "WindowsPowerShell\Modules")
    )
    $commandProcessor = [IO.Path]::GetFullPath(
        (Join-Path $systemDirectory "cmd.exe")
    )
    $temporaryDirectory = [IO.Path]::GetFullPath(
        [IO.Path]::GetTempPath()
    )
    $localApplicationData = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::LocalApplicationData
        )
    )
    foreach ($requiredDirectory in @(
        $systemDirectory,
        $windowsDirectory,
        $sharedModulePath,
        $systemModulePath,
        $temporaryDirectory,
        $localApplicationData
    )) {
        if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
            throw [TicketboxC07HeartbeatHelperException]::new(
                "heartbeat_helper_bootstrap_invalid",
                "C07 heartbeat helper 必需目录不存在：$requiredDirectory"
            )
        }
    }
    if (-not (Test-Path -LiteralPath $commandProcessor -PathType Leaf)) {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_bootstrap_invalid",
            "C07 heartbeat helper command processor 不存在。"
        )
    }

    $pathEntries = @(
        $systemDirectory,
        $windowsDirectory,
        (Join-Path $systemDirectory "Wbem"),
        $helperHome
    ) | Where-Object {
        Test-Path -LiteralPath $_ -PathType Container
    }
    $environment = @{
        "SystemRoot" = $windowsDirectory
        "WINDIR" = $windowsDirectory
        "ComSpec" = $commandProcessor
        "TEMP" = $temporaryDirectory
        "TMP" = $temporaryDirectory
        "LOCALAPPDATA" = $localApplicationData
        "PSModulePath" = "$sharedModulePath;$systemModulePath"
        "PATH" = ($pathEntries -join ";")
        "PATHEXT" = ".COM;.EXE;.BAT;.CMD"
    }
    return $environment
}

function New-TicketboxC07HeartbeatHelperNonce {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
        return ([BitConverter]::ToString($bytes)).Replace(
            "-",
            ""
        ).ToLowerInvariant()
    }
    finally {
        $generator.Dispose()
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function New-TicketboxC07HeartbeatHelperRequest {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 1200000)][int64]$RemainingCeilingMilliseconds,
        [Parameter(Mandatory = $true)][string]$RequestNonce,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-TicketboxC07DurableHeartbeatOperation $Operation $Label
    if ($RequestNonce -cnotmatch "^[0-9a-f]{64}$") {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_request_invalid",
            "$Label heartbeat helper nonce 无效。"
        )
    }
    $request = [ordered]@{
        schema = "ticketbox-c07-heartbeat-helper-request-v1"
        request_nonce = $RequestNonce
        operation_schema = [string]$Operation.Schema
        data_root = [string]$Operation.DataRoot
        operation_id = [string]$Operation.OperationId
        descriptor_sha256 = [string]$Operation.DescriptorSha256
        coordinator_binding_sha256 =
            [string]$Operation.CoordinatorBindingSha256
        coordinator_binding_sequence =
            [int64]$Operation.CoordinatorBindingSequence
        maintenance_attempt_id = [string]$Operation.MaintenanceAttemptId
        maintenance_attempt_sha256 =
            [string]$Operation.MaintenanceAttemptSha256
        maintenance_attempt_sequence =
            [int64]$Operation.MaintenanceAttemptSequence
        coordinator_pid = [int]$Operation.CoordinatorProcessId
        coordinator_started_filetime_high =
            [uint32]$Operation.CoordinatorStartedFileTimeHigh
        coordinator_started_filetime_low =
            [uint32]$Operation.CoordinatorStartedFileTimeLow
        deadline_utc = ([DateTime]$Operation.DeadlineUtc).ToUniversalTime().ToString(
            "o"
        )
        remaining_ceiling_ms = $RemainingCeilingMilliseconds
        host_full_control_accounts =
            [string[]]$Operation.HostFullControlAccounts
        host_owner_account = [string]$Operation.HostOwnerAccount
        installation_identity_acl_accounts =
            [string[]]$Operation.InstallationIdentityAclAccounts
        installation_identity_owner_account =
            [string]$Operation.InstallationIdentityOwnerAccount
        primary_lifecycle_lock_path =
            [string]$Operation.PrimaryLifecycleLockPath
        operation_lifecycle_lock_path =
            [string]$Operation.OperationLifecycleLockPath
    }
    return [string]($request | ConvertTo-Json -Depth 8 -Compress)
}

function Assert-TicketboxC07HeartbeatHelperResultShape {
    param(
        [Parameter(Mandatory = $true)][object]$Result,
        [Parameter(Mandatory = $true)][string]$RequestNonce,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][int]$ExitCode,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $expectedNames = @(
        "schema",
        "request_nonce",
        "status",
        "failure_code",
        "operation_id",
        "heartbeat_sequence"
    )
    $actualNames = @($Result.PSObject.Properties.Name)
    if (
        $actualNames.Count -ne $expectedNames.Count -or
        @($expectedNames | Where-Object { $_ -notin $actualNames }).Count -ne 0 -or
        @($actualNames | Where-Object { $_ -notin $expectedNames }).Count -ne 0 -or
        [string]$Result.schema -cne
            "ticketbox-c07-heartbeat-helper-result-v1" -or
        [string]$Result.request_nonce -cne $RequestNonce -or
        [string]$Result.operation_id -cne $OperationId -or
        ($Result.heartbeat_sequence -isnot [int] -and
            $Result.heartbeat_sequence -isnot [long]) -or
        [int64]$Result.heartbeat_sequence -lt -1
    ) {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_protocol_invalid",
            "$Label heartbeat helper result shape/binding 无效。"
        )
    }
    if ([string]$Result.status -ceq "ok") {
        if (
            $ExitCode -ne 0 -or
            -not [string]::IsNullOrEmpty([string]$Result.failure_code) -or
            [int64]$Result.heartbeat_sequence -lt 0
        ) {
            throw [TicketboxC07HeartbeatHelperException]::new(
                "heartbeat_helper_protocol_invalid",
                "$Label heartbeat helper success protocol 不一致。"
            )
        }
        return
    }
    if (
        [string]$Result.status -cne "failed" -or
        $ExitCode -eq 0 -or
        [string]$Result.failure_code -cnotmatch
            "^heartbeat_helper_[a-z0-9_]+$" -or
        [int64]$Result.heartbeat_sequence -ne -1
    ) {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_protocol_invalid",
            "$Label heartbeat helper failure protocol 不一致。"
        )
    }
}

function Invoke-TicketboxBoundedHeartbeatOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 3600000)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(100, 5000)][int]$SettlementMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-TicketboxC07DurableHeartbeatOperation $Operation $Label
    $operationRemaining = [int64](
        $Operation.GetRemainingCeilingMilliseconds()
    )
    $effectiveRemaining = [Math]::Min(
        $operationRemaining,
        [int64]$TimeoutMilliseconds
    )
    if ($effectiveRemaining -lt 1000) {
        throw [TicketboxC07HeartbeatHelperException]::new(
            "heartbeat_helper_deadline_exceeded",
            "$Label heartbeat helper 已耗尽 maintenance deadline。"
        )
    }

    $requestNonce = New-TicketboxC07HeartbeatHelperNonce
    $requestText = $null
    try {
        $requestText = New-TicketboxC07HeartbeatHelperRequest `
            -Operation $Operation `
            -RemainingCeilingMilliseconds $effectiveRemaining `
            -RequestNonce $requestNonce `
            -Label $Label
        $helperResult = $null
        try {
            $helperResult = Invoke-TicketboxBoundedNativeProcess `
                -FilePath (Get-TicketboxC07HeartbeatHelperExecutablePath) `
                -Arguments @(
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    (Get-TicketboxC07HeartbeatHelperScriptPath),
                    "-TicketboxC07HeartbeatHelper"
                ) `
                -TimeoutMilliseconds ([int]$effectiveRemaining) `
                -TerminationSettlementMilliseconds $SettlementMilliseconds `
                -Label "$Label heartbeat helper" `
                -StandardInputText ($requestText + "`n") `
                -ChildEnvironment (
                    New-TicketboxC07HeartbeatHelperChildEnvironment
                )
        }
        catch {
            $failureCode = [string](
                $_.Exception.Data["TicketboxC07FailureCode"]
            )
            if ($failureCode -ceq "tree_termination_unconfirmed") {
                throw $_.Exception
            }
            if ($failureCode -ceq "native_process_deadline_exceeded") {
                throw [TicketboxC07HeartbeatHelperException]::new(
                    "heartbeat_helper_deadline_exceeded",
                    "$Label heartbeat helper 超过允许时间。",
                    $_.Exception
                )
            }
            throw [TicketboxC07HeartbeatHelperException]::new(
                "heartbeat_helper_execution_failed",
                "$Label heartbeat helper 无法完成。",
                $_.Exception
            )
        }

        $lines = @(
            ([string]$helperResult.StandardOutput -split "`r?`n") |
                Where-Object { -not [string]::IsNullOrEmpty([string]$_) }
        )
        if (
            $lines.Count -ne 1 -or
            -not [string]::IsNullOrEmpty(
                [string]$helperResult.StandardError
            )
        ) {
            throw [TicketboxC07HeartbeatHelperException]::new(
                "heartbeat_helper_protocol_invalid",
                "$Label heartbeat helper 必须只返回一条 JSON result。"
            )
        }
        try {
            $resultPayload = $lines[0] | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw [TicketboxC07HeartbeatHelperException]::new(
                "heartbeat_helper_protocol_invalid",
                "$Label heartbeat helper result 不是有效 JSON。",
                $_.Exception.GetBaseException()
            )
        }
        Assert-TicketboxC07HeartbeatHelperResultShape `
            -Result $resultPayload `
            -RequestNonce $requestNonce `
            -OperationId ([string]$Operation.OperationId) `
            -ExitCode ([int]$helperResult.ExitCode) `
            -Label $Label
        if ([string]$resultPayload.status -ceq "failed") {
            throw [TicketboxC07HeartbeatHelperException]::new(
                ([string]$resultPayload.failure_code),
                "$Label heartbeat helper 拒绝续租。"
            )
        }
        return [int64]$resultPayload.heartbeat_sequence
    }
    finally {
        $requestText = $null
        $requestNonce = $null
    }
}

function Invoke-TicketboxBoundedNativeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label,
        [AllowEmptyString()][string]$StandardInputText,
        [AllowNull()][object]$HeartbeatOperation,
        [ValidateRange(1000, 30000)][int]$HeartbeatIntervalMilliseconds = 30000,
        [ValidateRange(100, 5000)][int]$HeartbeatSettlementMilliseconds = 1000,
        [ValidateRange(100, 30000)][int]$TerminationSettlementMilliseconds = 5000,
        [AllowNull()][System.Collections.IDictionary]$ChildEnvironment
    )

    $resolvedExecutable = [System.IO.Path]::GetFullPath($FilePath)
    if ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedExecutable) -cne 'File') {
        throw "$Label 可执行文件不是普通文件：$resolvedExecutable"
    }
    Assert-NoTicketboxAncestorReparsePoints $resolvedExecutable
    Initialize-TicketboxBoundedNativeProcessMethods
    $commandLine = ConvertTo-TicketboxNativeCommandLineArgument $resolvedExecutable
    $argumentCommandLine = (@(
        $Arguments | ForEach-Object {
            ConvertTo-TicketboxNativeCommandLineArgument ([string]$_)
        }
    ) -join ' ')
    if (-not [string]::IsNullOrEmpty($argumentCommandLine)) {
        $commandLine += " $argumentCommandLine"
    }
    $nativeProcess = $null
    $timer = $null
    $stdinWriteTask = $null
    $stdinFlushTask = $null
    $stdinClosed = $false
    $nativeFinished = $false
    $nativeTerminationConfirmed = $false
    try {
        $timer = [Diagnostics.Stopwatch]::StartNew()
        try {
            if ($PSBoundParameters.ContainsKey("ChildEnvironment")) {
                $nativeProcess = [TicketboxBoundedNativeProcess]::Start(
                    $resolvedExecutable,
                    $commandLine,
                    $ChildEnvironment
                )
            }
            else {
                $nativeProcess = [TicketboxBoundedNativeProcess]::Start(
                    $resolvedExecutable,
                    $commandLine
                )
            }
        }
        catch {
            throw "$Label 启动失败：$($_.Exception.GetBaseException().Message)"
        }
        $stdoutTask = $nativeProcess.StandardOutput.ReadToEndAsync()
        $stderrTask = $nativeProcess.StandardError.ReadToEndAsync()
        if ($PSBoundParameters.ContainsKey("StandardInputText")) {
            $stdinWriteTask = $nativeProcess.StandardInput.WriteAsync(
                $StandardInputText
            )
        }
        else {
            $nativeProcess.StandardInput.Close()
            $stdinClosed = $true
        }
        $inputFailure = $null
        $heartbeatFailure = $null
        $timedOut = $false
        $nextHeartbeatMilliseconds =
            [int64]$HeartbeatIntervalMilliseconds
        while ($true) {
            if (-not $stdinClosed) {
                try {
                    if (
                        $null -eq $stdinFlushTask -and
                        $stdinWriteTask.IsCompleted
                    ) {
                        [void]$stdinWriteTask.GetAwaiter().GetResult()
                        $stdinFlushTask =
                            $nativeProcess.StandardInput.FlushAsync()
                    }
                    if (
                        $null -ne $stdinFlushTask -and
                        $stdinFlushTask.IsCompleted
                    ) {
                        [void]$stdinFlushTask.GetAwaiter().GetResult()
                        $nativeProcess.StandardInput.Close()
                        $stdinClosed = $true
                    }
                }
                catch {
                    $inputFailure = $_
                    break
                }
            }
            $processExited = $nativeProcess.WaitForExit(0)
            $activeProcessCount = $nativeProcess.GetActiveProcessCount()
            if (
                $processExited -and
                $activeProcessCount -eq 0 -and
                $stdinClosed -and
                $stdoutTask.IsCompleted -and
                $stderrTask.IsCompleted
            ) {
                break
            }
            $elapsed = [int64]$timer.ElapsedMilliseconds
            $remaining = [int64]$TimeoutMilliseconds - $elapsed
            if ($remaining -le 0) {
                $timedOut = $true
                break
            }
            if (
                $elapsed -ge $nextHeartbeatMilliseconds -and
                $null -ne $HeartbeatOperation
            ) {
                try {
                    Invoke-TicketboxBoundedHeartbeatOperation `
                        -Operation $HeartbeatOperation `
                        -TimeoutMilliseconds ([int]$remaining) `
                        -SettlementMilliseconds $HeartbeatSettlementMilliseconds `
                        -Label $Label
                }
                catch {
                    $heartbeatFailure = $_
                    break
                }
                if (
                    [int64]$timer.ElapsedMilliseconds -ge
                    [int64]$TimeoutMilliseconds
                ) {
                    $timedOut = $true
                    break
                }
            }
            while ($nextHeartbeatMilliseconds -le $elapsed) {
                $nextHeartbeatMilliseconds +=
                    [int64]$HeartbeatIntervalMilliseconds
            }
            $untilHeartbeat = [Math]::Max(
                [int64]1,
                $nextHeartbeatMilliseconds - $elapsed
            )
            $waitMilliseconds = [Math]::Min(
                [Math]::Min($remaining, $untilHeartbeat),
                [int64]50
            )
            if ($processExited) {
                [Threading.Thread]::Sleep([int]$waitMilliseconds)
            }
            else {
                [void]$nativeProcess.WaitForExit([int]$waitMilliseconds)
            }
        }
        $timer.Stop()
        if (
            $null -ne $inputFailure -or
            $null -ne $heartbeatFailure -or
            $timedOut
        ) {
            if ($null -ne $inputFailure) {
                throw $inputFailure
            }
            if ($null -ne $heartbeatFailure) {
                throw $heartbeatFailure
            }
            $timeoutFailure = [TimeoutException]::new(
                "$Label 超过允许的 $TimeoutMilliseconds 毫秒，已终止。 " +
                "root_exited=$processExited active_processes=$activeProcessCount " +
                "stdin_closed=$stdinClosed stdout_completed=$($stdoutTask.IsCompleted) " +
                "stderr_completed=$($stderrTask.IsCompleted)"
            )
            $timeoutFailure.Data["TicketboxC07FailureCode"] =
                "native_process_deadline_exceeded"
            throw $timeoutFailure
        }
        $exitCode = $nativeProcess.GetExitCode()
        $standardOutput = [string]$stdoutTask.GetAwaiter().GetResult()
        $standardError = [string]$stderrTask.GetAwaiter().GetResult()
        $nativeFinished = $true
        return [pscustomobject]@{
            ExitCode = $exitCode
            StandardOutput = $standardOutput
            StandardError = $standardError
        }
    }
    catch {
        $operationFailure = $_.Exception
        if (
            $null -ne $nativeProcess -and
            -not $nativeFinished -and
            -not $nativeTerminationConfirmed
        ) {
            try {
                Stop-TicketboxBoundedNativeProcessTree `
                    -NativeProcess $nativeProcess `
                    -SettlementMilliseconds $TerminationSettlementMilliseconds
                $nativeTerminationConfirmed = $true
            }
            catch {
                throw (New-TicketboxNativeProcessTerminationAggregate `
                    -Label $Label `
                    -OperationFailure $operationFailure `
                    -TerminationFailure $_.Exception)
            }
        }
        throw $operationFailure
    }
    finally {
        if ($null -ne $timer -and $timer.IsRunning) {
            $timer.Stop()
        }
        if ($null -ne $nativeProcess) {
            $nativeProcess.Dispose()
        }
    }
}

function Remove-TicketboxProtectedPgPassArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [Parameter(Mandatory = $true)][string]$OwnerAccount,
        [ValidateRange(1, 1048576)][int]$MaximumBytes = 65536
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    Assert-NoTicketboxAncestorReparsePoints $fullPath
    if ((Get-TicketboxPathEntryKindNoFollow -Path $fullPath) -cne 'File') {
        throw "PostgreSQL 临时凭据不是普通文件：$fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.Length -gt $MaximumBytes
    ) {
        throw "PostgreSQL 临时凭据的类型或大小无效：$fullPath"
    }
    Assert-TicketboxExactFileAcl `
        -Path $fullPath `
        -Accounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if ((Get-TicketboxPathEntryKindNoFollow -Path $fullPath) -cne 'Missing') {
        throw "无法清理 PostgreSQL 临时凭据：$fullPath"
    }
}

function Get-TicketboxProtectedPgPassDirectory {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $parent = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
    if ([string]::IsNullOrWhiteSpace($parent)) {
        throw "Windows 未提供受保护的本机凭据根目录。"
    }
    $accounts = @($identity.User.Value)
    $ownerAccount = $identity.User.Value
    $directory = Join-Path $parent "TicketboxInstallerSecrets"
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $directory `
        -FullControlAccounts $accounts `
        -OwnerAccount $ownerAccount | Out-Null
    # The longest supported database-tool budget is one hour. Keep a second
    # hour of margin so scavenging can never delete another live invocation's
    # passfile while still recovering crash residue deterministically.
    $staleBefore = [DateTime]::UtcNow.AddHours(-2)
    foreach ($item in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
        $isPassfile = $item.Name -like '.ticketbox-pgpass-*'
        $isLegacyStaging = $item.Name -like '.ticketbox-protected-*.tmp'
        if (-not $isPassfile -and -not $isLegacyStaging) {
            throw "PostgreSQL 临时凭据目录含有未知对象：$($item.FullName)"
        }
        if ((Get-TicketboxPathEntryKindNoFollow -Path $item.FullName) -cne 'File') {
            throw "PostgreSQL 临时凭据不是普通文件：$($item.FullName)"
        }
        Assert-TicketboxExactFileAcl `
            -Path $item.FullName `
            -Accounts $accounts `
            -OwnerAccount $ownerAccount
        if ($item.LastWriteTimeUtc -lt $staleBefore) {
            Remove-TicketboxProtectedPgPassArtifact `
                -Path $item.FullName `
                -FullControlAccounts $accounts `
                -OwnerAccount $ownerAccount
        }
    }
    return [pscustomobject]@{
        Path = $directory
        FullControlAccounts = $accounts
        OwnerAccount = $ownerAccount
    }
}

function New-TicketboxProtectedPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password
    )

    if ([string]::IsNullOrWhiteSpace($Password)) {
        throw "PostgreSQL passfile 必须使用显式非空口令。"
    }
    $requiredUrl = ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    $builder = New-Object System.UriBuilder((ConvertTo-TicketboxLibpqUrl $requiredUrl))
    $username = [System.Uri]::UnescapeDataString($builder.UserName)
    $database = [System.Uri]::UnescapeDataString($builder.Path.TrimStart('/'))
    if (
        [string]::IsNullOrWhiteSpace($username) -or
        [string]::IsNullOrWhiteSpace($builder.Host) -or
        [string]::IsNullOrWhiteSpace($database)
    ) {
        throw "PostgreSQL passfile 缺少用户、主机或数据库。"
    }
    $directory = Get-TicketboxProtectedPgPassDirectory
    $passfile = Join-Path `
        $directory.Path `
        (".ticketbox-pgpass-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
    $port = if ($builder.Port -gt 0) { $builder.Port } else { 5432 }
    $fields = @($builder.Host, [string]$port, $database, $username, $Password) |
        ForEach-Object { ConvertTo-TicketboxPgPassField ([string]$_) }
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes(
        (($fields -join ':') + "`n")
    )
    $security = New-TicketboxProtectedFileSecurity `
        -FullControlAccounts $directory.FullControlAccounts `
        -OwnerAccount $directory.OwnerAccount
    try {
        $stream = New-TicketboxProtectedFileStream -Path $passfile -Security $security
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally { $stream.Dispose() }
        Assert-TicketboxExactFileAcl `
            -Path $passfile `
            -Accounts $directory.FullControlAccounts `
            -OwnerAccount $directory.OwnerAccount
    }
    catch {
        if (Test-Path -LiteralPath $passfile -PathType Leaf) {
            Remove-TicketboxProtectedPgPassArtifact `
                -Path $passfile `
                -FullControlAccounts $directory.FullControlAccounts `
                -OwnerAccount $directory.OwnerAccount
        }
        throw
    }
    return [pscustomobject]@{
        Path = $passfile
        FullControlAccounts = $directory.FullControlAccounts
        OwnerAccount = $directory.OwnerAccount
        DatabaseUrl = (ConvertTo-TicketboxLibpqUrl $requiredUrl)
    }
}

function Invoke-TicketboxWithPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $protected = New-TicketboxProtectedPgPassFile `
        -DatabaseUrl $DatabaseUrl `
        -Password $Password
    $previousPgEnvironment = @{}
    foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
        if ($item.Name -match '^(?i)PG') {
            $previousPgEnvironment[$item.Name] = [string]$item.Value
        }
    }
    $actionResult = $null
    try {
        foreach ($name in @($previousPgEnvironment.Keys)) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        $env:PGPASSFILE = $protected.Path
        $actionResults = @(& $Action $protected.DatabaseUrl)
        if ($actionResults.Count -ne 1) {
            throw "PostgreSQL 受保护操作必须返回且仅返回一个结果。"
        }
        $actionResult = $actionResults[0]
    }
    finally {
        try {
            Remove-TicketboxProtectedPgPassArtifact `
                -Path $protected.Path `
                -FullControlAccounts $protected.FullControlAccounts `
                -OwnerAccount $protected.OwnerAccount
        }
        finally {
            foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
                if ($item.Name -match '^(?i)PG') {
                    Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
                }
            }
            foreach ($entry in $previousPgEnvironment.GetEnumerator()) {
                [Environment]::SetEnvironmentVariable(
                    [string]$entry.Key,
                    [string]$entry.Value,
                    'Process'
                )
            }
        }
    }
    return $actionResult
}

function Invoke-TicketboxPgDumpCustom {
    param(
        [Parameter(Mandatory = $true)][string]$PgDumpPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        return Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $DatabaseUrl `
            -Password $Password `
            -Action {
                param([string]$ProtectedDatabaseUrl)
                $result = Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $PgDumpPath `
                    -Arguments @(
                        '--no-password',
                        '--lock-wait-timeout=30000',
                        '--format=custom',
                        '--file', $OutputPath,
                        '--dbname', $ProtectedDatabaseUrl
                    ) `
                    -TimeoutMilliseconds $TimeoutMilliseconds `
                    -Label 'pg_dump'
                return $result.ExitCode
            }
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-TicketboxPgRestoreList {
    param(
        [Parameter(Mandatory = $true)][string]$PgRestorePath,
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $result = Invoke-TicketboxBoundedNativeProcess `
        -FilePath $PgRestorePath `
        -Arguments @('--list', $ArchivePath) `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -Label 'pg_restore --list'
    return $result.ExitCode
}

function Assert-TicketboxConnectedPostgresDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$ExpectedDataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$ExpectedPort,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $result = Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $DatabaseUrl `
            -Password $Password `
            -Action {
                param([string]$ProtectedDatabaseUrl)
                $commandResult = Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $PsqlPath `
                    -Arguments @(
                        '--dbname', $ProtectedDatabaseUrl,
                        '--no-psqlrc',
                        '--no-password',
                        '--tuples-only',
                        '--no-align',
                        '--field-separator', "`t",
                        '--set', 'ON_ERROR_STOP=1'
                    ) `
                    -StandardInputText (
                        "SELECT current_setting('data_directory'), " +
                        "current_setting('listen_addresses'), " +
                        "current_setting('port');`n"
                    ) `
                    -TimeoutMilliseconds $TimeoutMilliseconds `
                    -Label 'psql PostgreSQL data-root verification'
                return [pscustomobject]@{
                    Output = @($commandResult.StandardOutput -split "`r?`n")
                    ExitCode = $commandResult.ExitCode
                }
            }
        $output = $result.Output
        $rc = $result.ExitCode
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($rc -ne 0) {
        throw "无法验证 PostgreSQL data_directory/listen_addresses/port（exit=$rc）：`n$output"
    }
    $lines = @($output | ForEach-Object { [string]$_ } | Where-Object { $_.Trim().Length -gt 0 })
    if ($lines.Count -ne 1) {
        throw "PostgreSQL 运行时边界返回格式异常，拒绝继续。"
    }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne 3) {
        throw "PostgreSQL 运行时边界字段数量异常，拒绝继续。"
    }
    $actual = ConvertTo-TicketboxCanonicalPath $fields[0].Trim()
    $expected = ConvertTo-TicketboxCanonicalPath $ExpectedDataRoot
    if (-not (Test-TicketboxPathEquals $actual $expected)) {
        throw "DATABASE_URL 连接的数据目录为 $actual，预期为 $expected，拒绝操作其它实例。"
    }
    if ([string]$fields[1].Trim() -cne "127.0.0.1") {
        throw "PostgreSQL 生效 listen_addresses 不是 127.0.0.1，拒绝继续。"
    }
    $actualPort = 0
    if (-not [int]::TryParse($fields[2].Trim(), [ref]$actualPort) -or $actualPort -ne $ExpectedPort) {
        throw "PostgreSQL 生效端口与安装配置不一致，拒绝继续。"
    }
}
