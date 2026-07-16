using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

public static class XpjTestProtectedFile
{
    private const uint GenericWrite = 0x40000000;
    private const uint WriteDac = 0x00040000;
    private const uint CreateNewDisposition = 1;
    private const uint FileAttributeNormal = 0x00000080;
    private const uint FileFlagWriteThrough = 0x80000000;
    private const uint SddlRevision1 = 1;

    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int Length;
        public IntPtr SecurityDescriptor;
        public int InheritHandle;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(
        string securityDescriptor,
        uint revision,
        out IntPtr securityDescriptorPointer,
        out uint securityDescriptorSize
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        FileShare shareMode,
        ref SecurityAttributes securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr LocalFree(IntPtr memory);

    public static FileStream CreateNew(string path, string currentUserSid)
    {
        string sid = new SecurityIdentifier(currentUserSid).Value;
        string sddl = string.Format(
            "O:{0}G:{0}D:P(A;;FA;;;{0})(A;;FA;;;SY)(A;;FA;;;BA)",
            sid
        );
        IntPtr descriptor;
        uint descriptorSize;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            SddlRevision1,
            out descriptor,
            out descriptorSize
        ))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Could not build the protected PostgreSQL authority file ACL."
            );
        }

        SafeFileHandle handle;
        int createError;
        try
        {
            SecurityAttributes attributes = new SecurityAttributes
            {
                Length = Marshal.SizeOf(typeof(SecurityAttributes)),
                SecurityDescriptor = descriptor,
                InheritHandle = 0,
            };
            handle = CreateFileW(
                path,
                GenericWrite | WriteDac,
                FileShare.None,
                ref attributes,
                CreateNewDisposition,
                FileAttributeNormal | FileFlagWriteThrough,
                IntPtr.Zero
            );
            createError = handle.IsInvalid ? Marshal.GetLastWin32Error() : 0;
        }
        finally
        {
            LocalFree(descriptor);
        }

        if (handle.IsInvalid)
        {
            handle.Dispose();
            throw new Win32Exception(
                createError,
                "Could not create the protected PostgreSQL authority file."
            );
        }
        try
        {
            return new FileStream(handle, FileAccess.Write, 4096, false);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }
}
