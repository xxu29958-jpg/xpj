#Requires -Version 5.1

function Initialize-TicketboxAtomicArtifactNativeMethods {
    if ($null -ne ("TicketboxAtomicArtifactNativeMethods" -as [type])) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using System.Text;

public static class TicketboxAtomicArtifactNativeMethods
{
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;
    private const uint CREATE_NEW = 1;
    private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
    private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
    private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    private const uint FILE_FLAG_WRITE_THROUGH = 0x80000000;
    private const uint MOVEFILE_WRITE_THROUGH = 0x00000008;

    private enum FILE_INFO_BY_HANDLE_CLASS
    {
        FileAttributeTagInfo = 9
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_ATTRIBUTE_TAG_INFO
    {
        public uint FileAttributes;
        public uint ReparseTag;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandleEx(
        SafeFileHandle file,
        FILE_INFO_BY_HANDLE_CLASS fileInformationClass,
        out FILE_ATTRIBUTE_TAG_INFO fileInformation,
        uint bufferSize
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(
        SafeFileHandle handle,
        StringBuilder path,
        uint pathLength,
        uint flags
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool MoveFileEx(
        string existingFileName,
        string newFileName,
        uint flags
    );

    public static string GetFinalPath(SafeFileHandle handle)
    {
        StringBuilder buffer = new StringBuilder(32768);
        uint result = GetFinalPathNameByHandle(
            handle,
            buffer,
            (uint)buffer.Capacity,
            0
        );
        if (result == 0 || result >= buffer.Capacity)
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "GetFinalPathNameByHandle"
            );
        }
        string path = buffer.ToString();
        if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            path = @"\\" + path.Substring(8);
        }
        else if (path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
        {
            path = path.Substring(4);
        }
        return Path.GetFullPath(path);
    }

    public static SafeFileHandle OpenDirectoryNoFollowNoDelete(string path)
    {
        SafeFileHandle handle = CreateFile(
            path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            IntPtr.Zero,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero
        );
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "CreateFile(directory)");
        }
        AssertHandleIsNotReparsePoint(handle);
        return handle;
    }

    public static SafeFileHandle CreateNewFileNoFollow(string path)
    {
        SafeFileHandle handle = CreateFile(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ,
            IntPtr.Zero,
            CREATE_NEW,
            FILE_ATTRIBUTE_NORMAL |
                FILE_FLAG_OPEN_REPARSE_POINT |
                FILE_FLAG_WRITE_THROUGH,
            IntPtr.Zero
        );
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "CreateFile(destination)");
        }
        AssertHandleIsNotReparsePoint(handle);
        return handle;
    }

    public static void AssertHandleIsNotReparsePoint(SafeFileHandle handle)
    {
        FILE_ATTRIBUTE_TAG_INFO info;
        uint size = (uint)Marshal.SizeOf(typeof(FILE_ATTRIBUTE_TAG_INFO));
        if (!GetFileInformationByHandleEx(
            handle,
            FILE_INFO_BY_HANDLE_CLASS.FileAttributeTagInfo,
            out info,
            size
        ))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "GetFileInformationByHandleEx"
            );
        }
        if ((info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
        {
            throw new IOException("Handle resolves to a reparse point.");
        }
    }

    public static void MoveDirectoryWriteThrough(
        string existingPath,
        string newPath
    )
    {
        if (!MoveFileEx(existingPath, newPath, MOVEFILE_WRITE_THROUGH))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "MoveFileEx(MOVEFILE_WRITE_THROUGH)"
            );
        }
    }
}
'@
}
