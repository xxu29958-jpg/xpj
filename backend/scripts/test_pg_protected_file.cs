using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

public static class XpjTestProtectedFile
{
    private const uint GenericRead = 0x80000000;
    private const uint GenericWrite = 0x40000000;
    private const uint WriteDac = 0x00040000;
    private const uint CreateNewDisposition = 1;
    private const uint OpenExistingDisposition = 3;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeNormal = 0x00000080;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileFlagWriteThrough = 0x80000000;
    private const uint SddlRevision1 = 1;

    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int Length;
        public IntPtr SecurityDescriptor;
        public int InheritHandle;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public uint LowDateTime;
        public uint HighDateTime;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public FileTime CreationTime;
        public FileTime LastAccessTime;
        public FileTime LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
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

    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode,
        SetLastError = true
    )]
    private static extern SafeFileHandle OpenFileW(
        string fileName,
        uint desiredAccess,
        FileShare shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out ByHandleFileInformation information
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr LocalFree(IntPtr memory);

    public static FileStream CreateNew(string path, string currentUserSid)
    {
        return CreateNew(
            path,
            currentUserSid,
            false,
            GenericWrite | WriteDac,
            FileShare.None,
            FileAccess.Write,
            "protected PostgreSQL authority file"
        );
    }

    public static FileStream CreateNewSharedLock(string path, string currentUserSid)
    {
        return CreateNew(
            path,
            currentUserSid,
            false,
            GenericRead | GenericWrite | WriteDac,
            FileShare.ReadWrite,
            FileAccess.ReadWrite,
            "protected PostgreSQL consumer lock"
        );
    }

    public static FileStream CreateNewInheritableProcessOutput(string path)
    {
        string currentUserSid = WindowsIdentity.GetCurrent().User.Value;
        return CreateNew(
            path,
            currentUserSid,
            true,
            GenericWrite | WriteDac,
            FileShare.Read,
            FileAccess.Write,
            "protected PostgreSQL process output"
        );
    }

    public static FileStream OpenReadShared(string path)
    {
        SafeFileHandle handle = OpenFileW(
            path,
            GenericRead,
            FileShare.ReadWrite,
            IntPtr.Zero,
            OpenExistingDisposition,
            FileFlagOpenReparsePoint,
            IntPtr.Zero
        );
        if (handle.IsInvalid)
        {
            int openError = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(
                openError,
                "Could not open the protected PostgreSQL authority file."
            );
        }
        try
        {
            ByHandleFileInformation information;
            if (!GetFileInformationByHandle(handle, out information))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Could not identify the protected PostgreSQL authority file."
                );
            }
            if ((information.FileAttributes & (
                FileAttributeDirectory | FileAttributeReparsePoint
            )) != 0)
            {
                throw new IOException(
                    "Protected PostgreSQL authority must be a regular non-reparse file."
                );
            }
            return new FileStream(handle, FileAccess.Read, 4096, false);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }

    private static FileStream CreateNew(
        string path,
        string currentUserSid,
        bool inheritHandle,
        uint desiredAccess,
        FileShare shareMode,
        FileAccess fileAccess,
        string label)
    {
        string sid = new SecurityIdentifier(currentUserSid).Value;
        string ownerSid = WindowsIdentity.GetCurrent().Owner.Value;
        string sddl = string.Format(
            "O:{0}G:{0}D:P(A;;FA;;;{1})(A;;FA;;;SY)(A;;FA;;;BA)",
            ownerSid,
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
                string.Format("Could not build the {0} ACL.", label)
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
                InheritHandle = inheritHandle ? 1 : 0,
            };
            handle = CreateFileW(
                path,
                desiredAccess,
                shareMode,
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
                string.Format("Could not create the {0}.", label)
            );
        }
        try
        {
            return new FileStream(handle, fileAccess, 4096, false);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }
}
