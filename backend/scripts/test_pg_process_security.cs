using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

public sealed partial class XpjTestProcessJob
{
    private const uint TokenAllAccess = 0x000F01FF;
    private const uint DisableMaxPrivilege = 0x00000001;
    private const int TokenUserClass = 1;
    private const int TokenDefaultDaclClass = 6;
    private const int AclSizeInformationClass = 2;
    private const uint AclRevision = 2;
    private const uint ObjectInheritAce = 0x00000001;
    private const uint GenericAll = 0x10000000;
    private const int ErrorInsufficientBuffer = 122;

    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes
    {
        public IntPtr Sid;
        public uint Attributes;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct TokenUserInformation
    {
        public SidAndAttributes User;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct TokenDefaultDaclInformation
    {
        public IntPtr DefaultDacl;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct AclSizeInformation
    {
        public uint AceCount;
        public uint AclBytesInUse;
        public uint AclBytesFree;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    private struct AceHeader
    {
        public byte AceType;
        public byte AceFlags;
        public ushort AceSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct AccessAllowedAce
    {
        public AceHeader Header;
        public uint Mask;
        public uint SidStart;
    }

    public int StartRestrictedProcess(
        string filePath,
        string[] arguments,
        System.IO.FileStream stdoutStream,
        System.IO.FileStream stderrStream)
    {
        return StartProcessCore(
            filePath,
            arguments,
            stdoutStream,
            stderrStream,
            null,
            true);
    }

    public int StartRestrictedProcess(
        string filePath,
        string[] arguments,
        System.IO.FileStream stdoutStream,
        System.IO.FileStream stderrStream,
        string standardInput)
    {
        return StartProcessCore(
            filePath,
            arguments,
            stdoutStream,
            stderrStream,
            standardInput,
            true);
    }

    private static ProcessInformation CreateAssignedProcess(
        bool restrictWindowsAdminAuthority,
        string applicationName,
        StringBuilder commandLine,
        bool inheritHandles,
        uint creationFlags,
        ref StartupInfoEx startupInfo)
    {
        ProcessInformation process;
        bool created;
        int createError;
        if (!restrictWindowsAdminAuthority)
        {
            created = CreateProcess(
                applicationName,
                commandLine,
                IntPtr.Zero,
                IntPtr.Zero,
                inheritHandles,
                creationFlags,
                IntPtr.Zero,
                null,
                ref startupInfo,
                out process);
            createError = created ? 0 : Marshal.GetLastWin32Error();
        }
        else
        {
            IntPtr restrictedToken = CreatePostgresRestrictedToken();
            try
            {
                created = CreateProcessAsUser(
                    restrictedToken,
                    applicationName,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    inheritHandles,
                    creationFlags,
                    IntPtr.Zero,
                    null,
                    ref startupInfo,
                    out process);
                createError = created ? 0 : Marshal.GetLastWin32Error();
            }
            finally
            {
                CloseHandle(restrictedToken);
            }
        }
        if (!created)
        {
            throw new Win32Exception(
                createError,
                "Cannot start PostgreSQL inside its lifecycle job.");
        }
        return process;
    }

    private static IntPtr CreatePostgresRestrictedToken()
    {
        IntPtr originalToken = IntPtr.Zero;
        IntPtr restrictedToken = IntPtr.Zero;
        IntPtr disabledSids = IntPtr.Zero;
        GCHandle administratorsPin = new GCHandle();
        GCHandle powerUsersPin = new GCHandle();
        bool completed = false;
        try
        {
            if (!OpenProcessToken(GetCurrentProcess(), TokenAllAccess, out originalToken))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot open the PostgreSQL lifecycle process token.");
            }
            byte[] administrators = GetSidBytes("S-1-5-32-544");
            byte[] powerUsers = GetSidBytes("S-1-5-32-547");
            administratorsPin = GCHandle.Alloc(administrators, GCHandleType.Pinned);
            powerUsersPin = GCHandle.Alloc(powerUsers, GCHandleType.Pinned);
            int sidEntrySize = Marshal.SizeOf(typeof(SidAndAttributes));
            disabledSids = Marshal.AllocHGlobal(sidEntrySize * 2);
            Marshal.StructureToPtr(
                new SidAndAttributes
                {
                    Sid = administratorsPin.AddrOfPinnedObject(),
                    Attributes = 0,
                },
                disabledSids,
                false);
            Marshal.StructureToPtr(
                new SidAndAttributes
                {
                    Sid = powerUsersPin.AddrOfPinnedObject(),
                    Attributes = 0,
                },
                IntPtr.Add(disabledSids, sidEntrySize),
                false);
            if (!CreateRestrictedToken(
                originalToken,
                DisableMaxPrivilege,
                2,
                disabledSids,
                0,
                IntPtr.Zero,
                0,
                IntPtr.Zero,
                out restrictedToken))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot create the restricted PostgreSQL process token.");
            }
            AddCurrentUserToTokenDacl(restrictedToken);
            completed = true;
            return restrictedToken;
        }
        finally
        {
            if (!completed && restrictedToken != IntPtr.Zero)
            {
                CloseHandle(restrictedToken);
            }
            if (disabledSids != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(disabledSids);
            }
            if (powerUsersPin.IsAllocated)
            {
                powerUsersPin.Free();
            }
            if (administratorsPin.IsAllocated)
            {
                administratorsPin.Free();
            }
            if (originalToken != IntPtr.Zero)
            {
                CloseHandle(originalToken);
            }
        }
    }

    private static byte[] GetSidBytes(string value)
    {
        var sid = new SecurityIdentifier(value);
        var bytes = new byte[sid.BinaryLength];
        sid.GetBinaryForm(bytes, 0);
        return bytes;
    }

    private static void AddCurrentUserToTokenDacl(IntPtr token)
    {
        IntPtr defaultDaclBuffer = IntPtr.Zero;
        IntPtr tokenUserBuffer = IntPtr.Zero;
        IntPtr newAcl = IntPtr.Zero;
        try
        {
            defaultDaclBuffer = ReadTokenInformation(token, TokenDefaultDaclClass);
            var defaultDacl = (TokenDefaultDaclInformation)Marshal.PtrToStructure(
                defaultDaclBuffer,
                typeof(TokenDefaultDaclInformation));
            if (defaultDacl.DefaultDacl == IntPtr.Zero)
            {
                throw new InvalidOperationException(
                    "Restricted PostgreSQL token has no default DACL.");
            }
            var aclSize = new AclSizeInformation();
            if (!GetAclInformation(
                defaultDacl.DefaultDacl,
                out aclSize,
                Marshal.SizeOf(typeof(AclSizeInformation)),
                AclSizeInformationClass))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot inspect the restricted PostgreSQL token DACL.");
            }
            tokenUserBuffer = ReadTokenInformation(token, TokenUserClass);
            var tokenUser = (TokenUserInformation)Marshal.PtrToStructure(
                tokenUserBuffer,
                typeof(TokenUserInformation));
            uint sidLength = GetLengthSid(tokenUser.User.Sid);
            int newAclSize = checked(
                (int)aclSize.AclBytesInUse
                + Marshal.SizeOf(typeof(AccessAllowedAce))
                + (int)sidLength
                - sizeof(uint));
            newAcl = Marshal.AllocHGlobal(newAclSize);
            if (!InitializeAcl(newAcl, checked((uint)newAclSize), AclRevision))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot initialize the restricted PostgreSQL token DACL.");
            }
            for (uint index = 0; index < aclSize.AceCount; index++)
            {
                IntPtr ace;
                if (!GetAce(defaultDacl.DefaultDacl, index, out ace))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "Cannot read the restricted PostgreSQL token DACL.");
                }
                var header = (AceHeader)Marshal.PtrToStructure(ace, typeof(AceHeader));
                if (!AddAce(newAcl, AclRevision, uint.MaxValue, ace, header.AceSize))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "Cannot copy the restricted PostgreSQL token DACL.");
                }
            }
            if (!AddAccessAllowedAceEx(
                newAcl,
                AclRevision,
                ObjectInheritAce,
                GenericAll,
                tokenUser.User.Sid))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot grant the current user access in the restricted token DACL.");
            }
            var updated = new TokenDefaultDaclInformation { DefaultDacl = newAcl };
            if (!SetTokenInformation(
                token,
                TokenDefaultDaclClass,
                ref updated,
                checked((uint)newAclSize)))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot publish the restricted PostgreSQL token DACL.");
            }
        }
        finally
        {
            if (newAcl != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(newAcl);
            }
            if (tokenUserBuffer != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(tokenUserBuffer);
            }
            if (defaultDaclBuffer != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(defaultDaclBuffer);
            }
        }
    }

    private static IntPtr ReadTokenInformation(IntPtr token, int informationClass)
    {
        uint required = 0;
        if (GetTokenInformation(token, informationClass, IntPtr.Zero, 0, out required))
        {
            throw new InvalidOperationException(
                "Windows returned token information without a destination buffer.");
        }
        int error = Marshal.GetLastWin32Error();
        if (error != ErrorInsufficientBuffer || required == 0)
        {
            throw new Win32Exception(
                error,
                "Cannot size the restricted PostgreSQL token information.");
        }
        IntPtr buffer = Marshal.AllocHGlobal(checked((int)required));
        if (!GetTokenInformation(token, informationClass, buffer, required, out required))
        {
            int readError = Marshal.GetLastWin32Error();
            Marshal.FreeHGlobal(buffer);
            throw new Win32Exception(
                readError,
                "Cannot read the restricted PostgreSQL token information.");
        }
        return buffer;
    }

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool OpenProcessToken(
        IntPtr process,
        uint desiredAccess,
        out IntPtr token);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool CreateRestrictedToken(
        IntPtr existingToken,
        uint flags,
        uint disableSidCount,
        IntPtr sidsToDisable,
        uint deletePrivilegeCount,
        IntPtr privilegesToDelete,
        uint restrictedSidCount,
        IntPtr sidsToRestrict,
        out IntPtr restrictedToken);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(
        IntPtr token,
        int informationClass,
        IntPtr information,
        uint informationLength,
        out uint returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool SetTokenInformation(
        IntPtr token,
        int informationClass,
        ref TokenDefaultDaclInformation information,
        uint informationLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetAclInformation(
        IntPtr acl,
        out AclSizeInformation information,
        int informationLength,
        int informationClass);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool InitializeAcl(
        IntPtr acl,
        uint aclLength,
        uint aclRevision);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetAce(IntPtr acl, uint index, out IntPtr ace);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool AddAce(
        IntPtr acl,
        uint aclRevision,
        uint startingAceIndex,
        IntPtr aceList,
        uint aceListLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool AddAccessAllowedAceEx(
        IntPtr acl,
        uint aclRevision,
        uint aceFlags,
        uint accessMask,
        IntPtr sid);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint GetLengthSid(IntPtr sid);

    [DllImport(
        "advapi32.dll",
        EntryPoint = "CreateProcessAsUserW",
        CharSet = CharSet.Unicode,
        SetLastError = true)]
    private static extern bool CreateProcessAsUser(
        IntPtr token,
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref StartupInfoEx startupInfo,
        out ProcessInformation processInformation);
}
