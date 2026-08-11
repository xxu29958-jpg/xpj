#Requires -Version 5.1

function Initialize-TicketboxWindowsTokenPrivilegeMethods {
    if ("TicketboxWindowsSecurityPrivilegeScope" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxWindowsLuid
{
    internal uint LowPart;
    internal int HighPart;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxWindowsLuidAndAttributes
{
    internal TicketboxWindowsLuid Luid;
    internal uint Attributes;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxWindowsTokenPrivileges
{
    internal uint PrivilegeCount;
    internal TicketboxWindowsLuidAndAttributes Privileges;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxWindowsPrivilegeSet
{
    internal uint PrivilegeCount;
    internal uint Control;
    internal TicketboxWindowsLuidAndAttributes Privilege;
}

public sealed class TicketboxWindowsSecurityPrivilegeScope : IDisposable
{
    private const uint TokenQuery = 0x0008;
    private const uint TokenAdjustPrivileges = 0x0020;
    private const uint PrivilegeEnabled = 0x00000002;
    private const uint PrivilegeSetAllNecessary = 0x00000001;
    private const int ErrorNotAllAssigned = 1300;
    private IntPtr tokenHandle;
    private TicketboxWindowsTokenPrivileges previousState;
    private bool restoreRequired;
    private bool disposed;

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(
        IntPtr processHandle,
        uint desiredAccess,
        out IntPtr tokenHandle);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool LookupPrivilegeValue(
        string systemName,
        string name,
        out TicketboxWindowsLuid luid);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool PrivilegeCheck(
        IntPtr clientToken,
        ref TicketboxWindowsPrivilegeSet requiredPrivileges,
        [MarshalAs(UnmanagedType.Bool)] out bool result);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr tokenHandle,
        [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TicketboxWindowsTokenPrivileges newState,
        int bufferLength,
        out TicketboxWindowsTokenPrivileges previousState,
        out int returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr tokenHandle,
        [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TicketboxWindowsTokenPrivileges newState,
        int bufferLength,
        IntPtr previousState,
        IntPtr returnLength);

    private TicketboxWindowsSecurityPrivilegeScope(IntPtr handle)
    {
        tokenHandle = handle;
    }

    public static bool IsEnabled(string privilegeName)
    {
        IntPtr handle;
        if (!OpenProcessToken(GetCurrentProcess(), TokenQuery, out handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        try
        {
            TicketboxWindowsLuid luid;
            if (!LookupPrivilegeValue(null, privilegeName, out luid))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            TicketboxWindowsPrivilegeSet required =
                new TicketboxWindowsPrivilegeSet
                {
                    PrivilegeCount = 1,
                    Control = PrivilegeSetAllNecessary,
                    Privilege = new TicketboxWindowsLuidAndAttributes
                    {
                        Luid = luid,
                        Attributes = PrivilegeEnabled
                    }
                };
            bool enabled;
            if (!PrivilegeCheck(handle, ref required, out enabled))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return enabled;
        }
        finally
        {
            CloseHandle(handle);
        }
    }

    public static TicketboxWindowsSecurityPrivilegeScope Enter(string privilegeName)
    {
        IntPtr handle;
        if (!OpenProcessToken(
            GetCurrentProcess(),
            TokenQuery | TokenAdjustPrivileges,
            out handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        TicketboxWindowsSecurityPrivilegeScope scope =
            new TicketboxWindowsSecurityPrivilegeScope(handle);
        try
        {
            TicketboxWindowsLuid luid;
            if (!LookupPrivilegeValue(null, privilegeName, out luid))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            TicketboxWindowsTokenPrivileges requested =
                new TicketboxWindowsTokenPrivileges();
            requested.PrivilegeCount = 1;
            requested.Privileges = new TicketboxWindowsLuidAndAttributes
            {
                Luid = luid,
                Attributes = PrivilegeEnabled
            };
            int returnLength;
            bool adjusted = AdjustTokenPrivileges(
                handle,
                false,
                ref requested,
                Marshal.SizeOf(typeof(TicketboxWindowsTokenPrivileges)),
                out scope.previousState,
                out returnLength);
            int error = Marshal.GetLastWin32Error();
            if (!adjusted || error == ErrorNotAllAssigned)
            {
                throw new Win32Exception(error);
            }
            scope.restoreRequired = true;
            return scope;
        }
        catch
        {
            scope.Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }
        disposed = true;
        Exception restoreFailure = null;
        if (restoreRequired)
        {
            bool restored = AdjustTokenPrivileges(
                tokenHandle,
                false,
                ref previousState,
                0,
                IntPtr.Zero,
                IntPtr.Zero);
            int restoreError = Marshal.GetLastWin32Error();
            if (!restored || restoreError == ErrorNotAllAssigned)
            {
                restoreFailure = new Win32Exception(restoreError);
            }
        }
        if (tokenHandle != IntPtr.Zero)
        {
            CloseHandle(tokenHandle);
            tokenHandle = IntPtr.Zero;
        }
        if (restoreFailure != null)
        {
            throw restoreFailure;
        }
    }
}
'@
}

function Test-TicketboxWindowsTokenPrivilegeEnabled {
    param(
        [ValidateNotNullOrEmpty()]
        [Parameter(Mandatory = $true)]
        [string]$PrivilegeName
    )

    Initialize-TicketboxWindowsTokenPrivilegeMethods
    return [TicketboxWindowsSecurityPrivilegeScope]::IsEnabled($PrivilegeName)
}
