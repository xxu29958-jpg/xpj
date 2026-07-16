using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public sealed class XpjTestDirectoryMoveHandle : IDisposable
{
    private const uint DeleteAccess = 0x00010000;
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private const int FileRenameInfo = 3;
    private const int FileDispositionInfo = 4;

    private IntPtr handle;

    private XpjTestDirectoryMoveHandle(IntPtr handle, string identity, bool isDirectory)
    {
        this.handle = handle;
        Identity = identity;
        IsDirectory = isDirectory;
    }

    public string Identity { get; private set; }
    public bool IsDirectory { get; private set; }

    public static XpjTestDirectoryMoveHandle Open(string path)
    {
        return OpenWithAccess(path, DeleteAccess | FileReadAttributes);
    }

    public static XpjTestDirectoryMoveHandle OpenIdentity(string path)
    {
        return OpenWithAccess(path, FileReadAttributes);
    }

    private static XpjTestDirectoryMoveHandle OpenWithAccess(
        string path,
        uint desiredAccess)
    {
        string fullPath = Path.GetFullPath(path);
        IntPtr opened = CreateFile(
            fullPath,
            desiredAccess,
            FileShareRead | FileShareWrite,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (opened == new IntPtr(-1))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Cannot lock the test PostgreSQL directory instance: " + fullPath);
        }
        ByHandleFileInformation information;
        if (!GetFileInformationByHandle(opened, out information))
        {
            var error = new Win32Exception(Marshal.GetLastWin32Error());
            CloseHandle(opened);
            throw error;
        }
        if ((information.FileAttributes & FileAttributeReparsePoint) != 0)
        {
            CloseHandle(opened);
            throw new IOException(
                "Test PostgreSQL directory instance must not be a reparse point: "
                + fullPath);
        }
        string identity = string.Format(
            "{0:x8}:{1:x8}:{2:x8}",
            information.VolumeSerialNumber,
            information.FileIndexHigh,
            information.FileIndexLow);
        return new XpjTestDirectoryMoveHandle(
            opened,
            identity,
            (information.FileAttributes & FileAttributeDirectory) != 0);
    }

    public static void DeleteTree(string path, string expectedIdentity)
    {
        string fullPath = Path.GetFullPath(path);
        using (var parentLease = XpjTestDirectoryPathLease.OpenParent(fullPath))
        using (var root = Open(fullPath))
        {
            if (!root.IsDirectory)
            {
                throw new IOException(
                    "Test PostgreSQL lifecycle deletion target is not a directory: "
                    + fullPath);
            }
            if (!string.Equals(
                root.Identity,
                expectedIdentity,
                StringComparison.OrdinalIgnoreCase))
            {
                throw new IOException(
                    "Test PostgreSQL lifecycle deletion target was replaced: "
                    + fullPath);
            }
            root.DeleteDirectoryContents(fullPath);
            root.DeleteOnClose();
        }
        if (Directory.Exists(fullPath) || File.Exists(fullPath))
        {
            throw new IOException(
                "Verified test PostgreSQL directory was not deleted: " + fullPath);
        }
    }

    public void DeleteOnClose()
    {
        EnsureOpen();
        var disposition = new FileDispositionInformation { DeleteFile = true };
        if (!SetFileDispositionInformationByHandle(
            handle,
            FileDispositionInfo,
            ref disposition,
            Marshal.SizeOf(typeof(FileDispositionInformation))))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Cannot delete the verified test PostgreSQL directory instance.");
        }
    }

    public void RenameTo(string destination)
    {
        EnsureOpen();
        string fullDestination = Path.GetFullPath(destination);
        using (var parentLease = XpjTestDirectoryPathLease.OpenParent(fullDestination))
        {
            if (Directory.Exists(fullDestination) || File.Exists(fullDestination))
            {
                throw new IOException("Deletion tombstone already exists: " + fullDestination);
            }

            byte[] nameBytes = Encoding.Unicode.GetBytes(fullDestination);
            int rootOffset = IntPtr.Size == 8 ? 8 : 4;
            int lengthOffset = rootOffset + IntPtr.Size;
            int nameOffset = lengthOffset + sizeof(int);
            // FILE_RENAME_INFO has a trailing WCHAR member. Keep an explicit NUL
            // in the native buffer even though FileNameLength excludes it.
            int bufferSize = nameOffset + nameBytes.Length + sizeof(char);
            IntPtr buffer = Marshal.AllocHGlobal(bufferSize);
            try
            {
                for (int offset = 0; offset < nameOffset; offset++)
                {
                    Marshal.WriteByte(buffer, offset, 0);
                }
                Marshal.WriteIntPtr(buffer, rootOffset, IntPtr.Zero);
                Marshal.WriteInt32(buffer, lengthOffset, nameBytes.Length);
                Marshal.Copy(nameBytes, 0, IntPtr.Add(buffer, nameOffset), nameBytes.Length);
                Marshal.WriteInt16(buffer, nameOffset + nameBytes.Length, 0);
                if (!SetFileInformationByHandle(
                    handle,
                    FileRenameInfo,
                    buffer,
                    (uint)bufferSize))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "Cannot atomically publish the test PostgreSQL deletion tombstone.");
                }
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }
    }

    public void Dispose()
    {
        if (handle != IntPtr.Zero && handle != new IntPtr(-1))
        {
            CloseHandle(handle);
            handle = IntPtr.Zero;
        }
        GC.SuppressFinalize(this);
    }

    private void EnsureOpen()
    {
        if (handle == IntPtr.Zero || handle == new IntPtr(-1))
        {
            throw new ObjectDisposedException("XpjTestDirectoryMoveHandle");
        }
    }

    private void DeleteDirectoryContents(string directoryPath)
    {
        EnsureOpen();
        foreach (string entryPath in Directory.GetFileSystemEntries(directoryPath))
        {
            using (var entry = Open(entryPath))
            {
                if (entry.IsDirectory)
                {
                    entry.DeleteDirectoryContents(entryPath);
                }
                entry.DeleteOnClose();
            }
            if (Directory.Exists(entryPath) || File.Exists(entryPath))
            {
                throw new IOException(
                    "Verified test PostgreSQL child was not deleted: " + entryPath);
            }
        }
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

    [StructLayout(LayoutKind.Sequential)]
    private struct FileDispositionInformation
    {
        [MarshalAs(UnmanagedType.Bool)]
        public bool DeleteFile;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "SetFileInformationByHandle",
        SetLastError = true)]
    private static extern bool SetFileInformationByHandle(
        IntPtr file,
        int fileInformationClass,
        IntPtr fileInformation,
        uint bufferSize);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "SetFileInformationByHandle",
        SetLastError = true)]
    private static extern bool SetFileDispositionInformationByHandle(
        IntPtr file,
        int fileInformationClass,
        ref FileDispositionInformation fileInformation,
        int bufferSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        IntPtr file,
        out ByHandleFileInformation fileInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
}

public sealed class XpjTestDirectoryPathLease : IDisposable
{
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private readonly List<IntPtr> handles;

    private XpjTestDirectoryPathLease(List<IntPtr> handles)
    {
        this.handles = handles;
    }

    public static XpjTestDirectoryPathLease OpenPath(string path)
    {
        return OpenChain(Path.GetFullPath(path));
    }

    public static XpjTestDirectoryPathLease OpenParent(string path)
    {
        string parent = Path.GetDirectoryName(Path.GetFullPath(path));
        if (string.IsNullOrEmpty(parent))
        {
            throw new IOException("Test PostgreSQL path has no parent directory: " + path);
        }
        return OpenChain(parent);
    }

    public void Dispose()
    {
        for (int index = handles.Count - 1; index >= 0; index--)
        {
            CloseHandle(handles[index]);
        }
        handles.Clear();
        GC.SuppressFinalize(this);
    }

    private static XpjTestDirectoryPathLease OpenChain(string path)
    {
        string root = Path.GetPathRoot(path);
        if (string.IsNullOrEmpty(root))
        {
            throw new IOException("Test PostgreSQL path has no filesystem root: " + path);
        }
        var opened = new List<IntPtr>();
        try
        {
            string current = root;
            OpenDirectory(current, opened);
            string relative = path.Substring(root.Length);
            foreach (string component in relative.Split(
                new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar },
                StringSplitOptions.RemoveEmptyEntries))
            {
                current = Path.Combine(current, component);
                OpenDirectory(current, opened);
            }
            return new XpjTestDirectoryPathLease(opened);
        }
        catch
        {
            for (int index = opened.Count - 1; index >= 0; index--)
            {
                CloseHandle(opened[index]);
            }
            throw;
        }
    }

    private static void OpenDirectory(string path, List<IntPtr> opened)
    {
        IntPtr handle = CreateFile(
            path,
            FileReadAttributes,
            FileShareRead | FileShareWrite,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (handle == new IntPtr(-1))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Cannot lock the test PostgreSQL path component: " + path);
        }
        ByHandleFileInformation information;
        if (!GetFileInformationByHandle(handle, out information))
        {
            var error = new Win32Exception(Marshal.GetLastWin32Error());
            CloseHandle(handle);
            throw error;
        }
        if (
            (information.FileAttributes & FileAttributeDirectory) == 0 ||
            (information.FileAttributes & FileAttributeReparsePoint) != 0)
        {
            CloseHandle(handle);
            throw new IOException(
                "Test PostgreSQL path component must be a real directory: " + path);
        }
        opened.Add(handle);
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

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        IntPtr file,
        out ByHandleFileInformation fileInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
}

public static class XpjTestWindowsPath
{
    public static string GetLegacyTempPath()
    {
        var buffer = new StringBuilder(32768);
        uint length = GetTempPath((uint)buffer.Capacity, buffer);
        if (length == 0 || length >= (uint)buffer.Capacity)
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Cannot resolve the shared test PostgreSQL temporary directory.");
        }
        return buffer.ToString();
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetTempPath(uint bufferLength, StringBuilder buffer);
}
