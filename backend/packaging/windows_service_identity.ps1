#Requires -Version 5.1

$script:TicketboxLocalServiceLogonAccount = "NT AUTHORITY\LocalService"
$script:TicketboxServiceSidTypeByName = @{
    none = [uint32]0
    unrestricted = [uint32]1
    restricted = [uint32]3
}

function Assert-TicketboxServiceIdentityName([string]$Name) {
    if (
        [string]::IsNullOrWhiteSpace($Name) -or
        $Name.Length -gt 256 -or
        $Name.IndexOfAny([char[]]@(0, 47, 92)) -ge 0
    ) {
        throw "Invalid Windows service name for identity handling."
    }
    return $Name
}

function Get-TicketboxServiceResourcePrincipal([string]$Name) {
    $serviceName = Assert-TicketboxServiceIdentityName $Name
    return "NT SERVICE\$serviceName"
}

function ConvertTo-TicketboxServiceLogonAccount {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Account,
        [switch]$AllowLegacyVirtualAccount
    )

    $serviceName = Assert-TicketboxServiceIdentityName $Name
    if ([string]::Equals(
        $Account,
        $script:TicketboxLocalServiceLogonAccount,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        return $script:TicketboxLocalServiceLogonAccount
    }

    $legacyAccount = Get-TicketboxServiceResourcePrincipal $serviceName
    if (
        $AllowLegacyVirtualAccount -and
        [string]::Equals(
            $Account,
            $legacyAccount,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        return $legacyAccount
    }

    throw "Unsupported Windows service logon account."
}

function ConvertTo-TicketboxServiceSidTypeValue([string]$SidType) {
    if ([string]::IsNullOrWhiteSpace($SidType)) {
        throw "Windows service SID type is required."
    }
    $normalized = $SidType.Trim().ToLowerInvariant()
    if (-not $script:TicketboxServiceSidTypeByName.ContainsKey($normalized)) {
        throw "Unsupported Windows service SID type: $SidType"
    }
    return [uint32]$script:TicketboxServiceSidTypeByName[$normalized]
}

function ConvertFrom-TicketboxServiceSidTypeValue([uint32]$SidType) {
    switch ($SidType) {
        0 { return "none" }
        1 { return "unrestricted" }
        3 { return "restricted" }
        default { throw "SCM returned an unsupported service SID type: $SidType" }
    }
}

if (-not ("Ticketbox.Windows.ServiceIdentityNative" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Ticketbox.Windows
{
    public static class ServiceIdentityNative
    {
        private const uint SC_MANAGER_CONNECT = 0x0001;
        private const uint SERVICE_QUERY_CONFIG = 0x0001;
        private const uint SERVICE_CHANGE_CONFIG = 0x0002;
        private const uint SERVICE_CONFIG_SERVICE_SID_INFO = 5;
        private const int ERROR_INSUFFICIENT_BUFFER = 122;

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr OpenSCManager(
            string machineName,
            string databaseName,
            uint desiredAccess);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr OpenService(
            IntPtr serviceManager,
            string serviceName,
            uint desiredAccess);

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool QueryServiceConfig2(
            IntPtr service,
            uint infoLevel,
            IntPtr buffer,
            uint bufferSize,
            out uint bytesNeeded);

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ChangeServiceConfig2(
            IntPtr service,
            uint infoLevel,
            IntPtr info);

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseServiceHandle(IntPtr serviceHandle);

        private static Win32Exception Error(string operation)
        {
            return new Win32Exception(
                Marshal.GetLastWin32Error(),
                operation + " failed");
        }

        public static uint QuerySidType(string serviceName)
        {
            IntPtr manager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;
            IntPtr buffer = IntPtr.Zero;
            try
            {
                manager = OpenSCManager(null, null, SC_MANAGER_CONNECT);
                if (manager == IntPtr.Zero)
                    throw Error("OpenSCManagerW");

                service = OpenService(manager, serviceName, SERVICE_QUERY_CONFIG);
                if (service == IntPtr.Zero)
                    throw Error("OpenServiceW");

                uint bytesNeeded;
                bool probe = QueryServiceConfig2(
                    service,
                    SERVICE_CONFIG_SERVICE_SID_INFO,
                    IntPtr.Zero,
                    0,
                    out bytesNeeded);
                int probeError = Marshal.GetLastWin32Error();
                if (probe || probeError != ERROR_INSUFFICIENT_BUFFER)
                    throw new Win32Exception(
                        probeError,
                        "QueryServiceConfig2W size probe failed");
                if (bytesNeeded < sizeof(uint) || bytesNeeded > 4096)
                    throw new InvalidOperationException(
                        "QueryServiceConfig2W returned an invalid buffer size");

                buffer = Marshal.AllocHGlobal(checked((int)bytesNeeded));
                if (!QueryServiceConfig2(
                    service,
                    SERVICE_CONFIG_SERVICE_SID_INFO,
                    buffer,
                    bytesNeeded,
                    out bytesNeeded))
                    throw Error("QueryServiceConfig2W");

                return unchecked((uint)Marshal.ReadInt32(buffer));
            }
            finally
            {
                if (buffer != IntPtr.Zero)
                    Marshal.FreeHGlobal(buffer);
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (manager != IntPtr.Zero)
                    CloseServiceHandle(manager);
            }
        }

        public static void SetSidType(string serviceName, uint sidType)
        {
            IntPtr manager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;
            IntPtr info = IntPtr.Zero;
            try
            {
                manager = OpenSCManager(null, null, SC_MANAGER_CONNECT);
                if (manager == IntPtr.Zero)
                    throw Error("OpenSCManagerW");

                service = OpenService(
                    manager,
                    serviceName,
                    SERVICE_CHANGE_CONFIG | SERVICE_QUERY_CONFIG);
                if (service == IntPtr.Zero)
                    throw Error("OpenServiceW");

                info = Marshal.AllocHGlobal(sizeof(uint));
                Marshal.WriteInt32(info, unchecked((int)sidType));
                if (!ChangeServiceConfig2(
                    service,
                    SERVICE_CONFIG_SERVICE_SID_INFO,
                    info))
                    throw Error("ChangeServiceConfig2W");
            }
            finally
            {
                if (info != IntPtr.Zero)
                    Marshal.FreeHGlobal(info);
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (manager != IntPtr.Zero)
                    CloseServiceHandle(manager);
            }
        }
    }
}
"@
}

function Invoke-TicketboxNativeServiceSidTypeQuery([string]$Name) {
    return [Ticketbox.Windows.ServiceIdentityNative]::QuerySidType($Name)
}

function Invoke-TicketboxNativeServiceSidTypeSet {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][uint32]$SidType
    )
    [Ticketbox.Windows.ServiceIdentityNative]::SetSidType($Name, $SidType)
}

function Get-TicketboxServiceSidType([string]$Name) {
    $serviceName = Assert-TicketboxServiceIdentityName $Name
    $value = Invoke-TicketboxNativeServiceSidTypeQuery $serviceName
    return ConvertFrom-TicketboxServiceSidTypeValue ([uint32]$value)
}

function Assert-TicketboxServiceSidType {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedSidType
    )

    $expected = ConvertFrom-TicketboxServiceSidTypeValue `
        (ConvertTo-TicketboxServiceSidTypeValue $ExpectedSidType)
    $actual = Get-TicketboxServiceSidType $Name
    if ($actual -cne $expected) {
        throw "Windows service SID type mismatch for ${Name}: actual=$actual expected=$expected"
    }
}

function Set-TicketboxServiceSidType {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$SidType
    )

    $serviceName = Assert-TicketboxServiceIdentityName $Name
    $value = ConvertTo-TicketboxServiceSidTypeValue $SidType
    Invoke-TicketboxNativeServiceSidTypeSet `
        -Name $serviceName `
        -SidType $value
    Assert-TicketboxServiceSidType `
        -Name $serviceName `
        -ExpectedSidType $SidType
}

function New-TicketboxServiceIdentityShape {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$LogonAccount,
        [Parameter(Mandatory = $true)][string]$SidType,
        [switch]$AllowLegacyVirtualAccount
    )

    return [pscustomobject]@{
        LogonAccount = ConvertTo-TicketboxServiceLogonAccount `
            -Name $Name `
            -Account $LogonAccount `
            -AllowLegacyVirtualAccount:$AllowLegacyVirtualAccount
        SidType = ConvertFrom-TicketboxServiceSidTypeValue `
            (ConvertTo-TicketboxServiceSidTypeValue $SidType)
    }
}

function Get-TicketboxServiceIdentitySnapshot([string]$Name) {
    $serviceName = Assert-TicketboxServiceIdentityName $Name
    $escaped = $serviceName.Replace("'", "''")
    $record = Get-CimInstance `
        -ClassName Win32_Service `
        -Filter "Name='$escaped'" `
        -ErrorAction Stop
    if ($null -eq $record) {
        throw "Windows service does not exist: $serviceName"
    }
    return [pscustomobject]@{
        Name = $serviceName
        LogonAccount = [string]$record.StartName
        SidType = Get-TicketboxServiceSidType $serviceName
    }
}

function Assert-TicketboxServiceIdentityShape {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object[]]$AllowedShapes
    )

    if ($AllowedShapes.Count -eq 0) {
        throw "At least one allowed Windows service identity shape is required."
    }
    $actual = Get-TicketboxServiceIdentitySnapshot $Name
    foreach ($shape in $AllowedShapes) {
        if (
            $null -ne $shape -and
            [string]::Equals(
                [string]$actual.LogonAccount,
                [string]$shape.LogonAccount,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -and
            [string]$actual.SidType -ceq [string]$shape.SidType
        ) {
            return $actual
        }
    }
    $expected = @(
        $AllowedShapes |
            ForEach-Object { "$([string]$_.LogonAccount)|$([string]$_.SidType)" }
    ) -join ","
    throw "Windows service identity mismatch for ${Name}: actual=$($actual.LogonAccount)|$($actual.SidType) expected=$expected"
}
