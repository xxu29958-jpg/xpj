using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public sealed partial class XpjTestProcessJob : IDisposable
{
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private const uint GenericRead = 0x80000000;
    private const uint GenericWrite = 0x40000000;
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint FileShareDelete = 0x00000004;
    private const uint CreateAlways = 2;
    private const uint OpenExisting = 3;
    private const uint FileAttributeNormal = 0x00000080;
    private const uint ExtendedStartupInfoPresent = 0x00080000;
    private const uint CreateNoWindow = 0x08000000;
    private const uint StartfUseStdHandles = 0x00000100;
    private const uint HandleFlagInherit = 0x00000001;
    private const uint WaitObject0 = 0x00000000;
    private const uint WaitTimeout = 0x00000102;
    private static readonly IntPtr ProcThreadAttributeHandleList = new IntPtr(0x00020002);
    private static readonly IntPtr ProcThreadAttributeJobList = new IntPtr(0x0002000D);
    private IntPtr handle;
    private IntPtr startedProcessHandle;
    private int startedProcessId;

    public XpjTestProcessJob()
    {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        var limits = new JobObjectExtendedLimitInformation();
        limits.BasicLimitInformation.LimitFlags = JobObjectLimitKillOnJobClose;
        if (!SetInformationJobObject(
            handle,
            9,
            ref limits,
            Marshal.SizeOf(typeof(JobObjectExtendedLimitInformation))))
        {
            var error = new Win32Exception(Marshal.GetLastWin32Error());
            CloseHandle(handle);
            handle = IntPtr.Zero;
            throw error;
        }
    }

    ~XpjTestProcessJob()
    {
        Dispose(false);
    }

    public void Terminate(uint exitCode)
    {
        if (!TerminateJobObject(handle, exitCode))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public bool ContainsProcess(IntPtr processHandle)
    {
        EnsureOpen();
        bool result;
        if (!IsProcessInJob(processHandle, handle, out result))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return result;
    }

    public bool ContainsStartedProcess()
    {
        EnsureStartedProcess();
        return ContainsProcess(startedProcessHandle);
    }

    public bool IsStartedProcessRunning()
    {
        EnsureStartedProcess();
        uint result = WaitForSingleObject(startedProcessHandle, 0);
        if (result == WaitObject0)
        {
            return false;
        }
        if (result == WaitTimeout)
        {
            return true;
        }
        throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    public int StartProcess(
        string filePath,
        string[] arguments,
        string stdoutPath,
        string stderrPath)
    {
        return StartProcess(filePath, arguments, stdoutPath, stderrPath, null);
    }

    public int StartProcess(
        string filePath,
        string[] arguments,
        string stdoutPath,
        string stderrPath,
        string standardInput)
    {
        EnsureOpen();
        string fullFilePath = Path.GetFullPath(filePath);
        string fullStdoutPath = Path.GetFullPath(stdoutPath);
        string fullStderrPath = Path.GetFullPath(stderrPath);
        if (startedProcessHandle != IntPtr.Zero)
        {
            throw new InvalidOperationException(
                "This lifecycle job already owns a started process.");
        }
        var inheritable = new SecurityAttributes();
        inheritable.Length = Marshal.SizeOf(typeof(SecurityAttributes));
        inheritable.InheritHandle = true;
        IntPtr stdoutHandle = CreateFile(
            fullStdoutPath,
            GenericWrite,
            FileShareRead | FileShareWrite | FileShareDelete,
            ref inheritable,
            CreateAlways,
            FileAttributeNormal,
            IntPtr.Zero);
        ThrowIfInvalidHandle(stdoutHandle, "Cannot open PostgreSQL stdout log");
        IntPtr stderrHandle = IntPtr.Zero;
        IntPtr stdinHandle = IntPtr.Zero;
        IntPtr stdinWriteHandle = IntPtr.Zero;
        IntPtr attributeList = IntPtr.Zero;
        IntPtr jobList = IntPtr.Zero;
        IntPtr handleList = IntPtr.Zero;
        bool attributeListInitialized = false;
        try
        {
            stderrHandle = CreateFile(
                fullStderrPath,
                GenericWrite,
                FileShareRead | FileShareWrite | FileShareDelete,
                ref inheritable,
                CreateAlways,
                FileAttributeNormal,
                IntPtr.Zero);
            ThrowIfInvalidHandle(stderrHandle, "Cannot open PostgreSQL stderr log");
            if (standardInput == null)
            {
                stdinHandle = CreateFile(
                    "NUL",
                    GenericRead,
                    FileShareRead | FileShareWrite,
                    ref inheritable,
                    OpenExisting,
                    FileAttributeNormal,
                    IntPtr.Zero);
                ThrowIfInvalidHandle(stdinHandle, "Cannot open PostgreSQL stdin");
            }
            else
            {
                if (!CreatePipe(
                    out stdinHandle,
                    out stdinWriteHandle,
                    ref inheritable,
                    0))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "Cannot create PostgreSQL stdin pipe.");
                }
                if (!SetHandleInformation(
                    stdinWriteHandle,
                    HandleFlagInherit,
                    0))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "Cannot protect PostgreSQL stdin writer.");
                }
            }

            IntPtr attributeSize = IntPtr.Zero;
            InitializeProcThreadAttributeList(
                IntPtr.Zero,
                2,
                0,
                ref attributeSize);
            attributeList = Marshal.AllocHGlobal(attributeSize);
            if (!InitializeProcThreadAttributeList(
                attributeList,
                2,
                0,
                ref attributeSize))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            handleList = Marshal.AllocHGlobal(IntPtr.Size * 3);
            Marshal.WriteIntPtr(handleList, 0, stdinHandle);
            Marshal.WriteIntPtr(handleList, IntPtr.Size, stdoutHandle);
            Marshal.WriteIntPtr(handleList, IntPtr.Size * 2, stderrHandle);
            if (!UpdateProcThreadAttribute(
                attributeList,
                0,
                ProcThreadAttributeHandleList,
                handleList,
                new IntPtr(IntPtr.Size * 3),
                IntPtr.Zero,
                IntPtr.Zero))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            attributeListInitialized = true;
            jobList = Marshal.AllocHGlobal(IntPtr.Size);
            Marshal.WriteIntPtr(jobList, handle);
            if (!UpdateProcThreadAttribute(
                attributeList,
                0,
                ProcThreadAttributeJobList,
                jobList,
                new IntPtr(IntPtr.Size),
                IntPtr.Zero,
                IntPtr.Zero))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }

            var startup = new StartupInfoEx();
            startup.StartupInfo.Size = Marshal.SizeOf(typeof(StartupInfoEx));
            startup.StartupInfo.Flags = StartfUseStdHandles;
            startup.StartupInfo.StandardInput = stdinHandle;
            startup.StartupInfo.StandardOutput = stdoutHandle;
            startup.StartupInfo.StandardError = stderrHandle;
            startup.AttributeList = attributeList;
            var commandLine = new StringBuilder(QuoteWindowsArgument(fullFilePath));
            foreach (string argument in arguments)
            {
                commandLine.Append(' ');
                commandLine.Append(QuoteWindowsArgument(argument));
            }
            ProcessInformation process;
            if (!CreateProcess(
                fullFilePath,
                commandLine,
                IntPtr.Zero,
                IntPtr.Zero,
                true,
                ExtendedStartupInfoPresent | CreateNoWindow,
                IntPtr.Zero,
                null,
                ref startup,
                out process))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "Cannot start PostgreSQL inside its lifecycle job.");
            }
            bool retainedProcessHandle = false;
            try
            {
                bool contained;
                if (!IsProcessInJob(process.Process, handle, out contained) || !contained)
                {
                    TerminateProcess(process.Process, 1);
                    throw new IOException(
                        "PostgreSQL process was not atomically assigned to its lifecycle job.");
                }
                startedProcessHandle = process.Process;
                startedProcessId = checked((int)process.ProcessId);
                if (standardInput != null)
                {
                    WriteStandardInput(stdinWriteHandle, standardInput);
                    CloseIfValid(stdinWriteHandle);
                    stdinWriteHandle = IntPtr.Zero;
                }
                retainedProcessHandle = true;
                return startedProcessId;
            }
            finally
            {
                CloseHandle(process.Thread);
                if (!retainedProcessHandle)
                {
                    CloseHandle(process.Process);
                }
            }
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
            if (jobList != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(jobList);
            }
            if (handleList != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(handleList);
            }
            CloseIfValid(stdinHandle);
            CloseIfValid(stdinWriteHandle);
            CloseIfValid(stderrHandle);
            CloseIfValid(stdoutHandle);
        }
    }

    public bool WaitForStartedProcess(int milliseconds)
    {
        EnsureStartedProcess();
        uint result = WaitForSingleObject(startedProcessHandle, checked((uint)milliseconds));
        if (result == WaitObject0)
        {
            return true;
        }
        if (result == WaitTimeout)
        {
            return false;
        }
        throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    public int GetStartedProcessExitCode()
    {
        EnsureStartedProcess();
        uint exitCode;
        if (!GetExitCodeProcess(startedProcessHandle, out exitCode))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return checked((int)exitCode);
    }

    public void PreserveProcessesOnClose()
    {
        EnsureOpen();
        var limits = new JobObjectExtendedLimitInformation();
        if (!SetInformationJobObject(
            handle,
            9,
            ref limits,
            Marshal.SizeOf(typeof(JobObjectExtendedLimitInformation))))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    private void Dispose(bool disposing)
    {
        if (handle != IntPtr.Zero)
        {
            CloseHandle(handle);
            handle = IntPtr.Zero;
        }
        if (startedProcessHandle != IntPtr.Zero)
        {
            CloseHandle(startedProcessHandle);
            startedProcessHandle = IntPtr.Zero;
            startedProcessId = 0;
        }
    }

    private void EnsureOpen()
    {
        if (handle == IntPtr.Zero)
        {
            throw new ObjectDisposedException("XpjTestProcessJob");
        }
    }

    private void EnsureStartedProcess()
    {
        EnsureOpen();
        if (startedProcessHandle == IntPtr.Zero || startedProcessId <= 0)
        {
            throw new InvalidOperationException(
                "This lifecycle job does not own a started process.");
        }
    }

    private static void ThrowIfInvalidHandle(IntPtr fileHandle, string message)
    {
        if (fileHandle == IntPtr.Zero || fileHandle == new IntPtr(-1))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), message);
        }
    }

    private static void CloseIfValid(IntPtr fileHandle)
    {
        if (fileHandle != IntPtr.Zero && fileHandle != new IntPtr(-1))
        {
            CloseHandle(fileHandle);
        }
    }

    private static void WriteStandardInput(IntPtr handle, string content)
    {
        byte[] bytes = new UTF8Encoding(false).GetBytes(content);
        uint written;
        if (!WriteFile(
            handle,
            bytes,
            checked((uint)bytes.Length),
            out written,
            IntPtr.Zero))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Cannot write PostgreSQL standard input.");
        }
        if (written != checked((uint)bytes.Length))
        {
            throw new IOException("PostgreSQL standard input was only partially written.");
        }
    }

    private static string QuoteWindowsArgument(string argument)
    {
        if (argument.Length > 0 && argument.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
        {
            return argument;
        }
        var result = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char character in argument)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }
            if (character == '"')
            {
                result.Append('\\', (backslashes * 2) + 1);
            }
            else
            {
                result.Append('\\', backslashes);
            }
            result.Append(character);
            backslashes = 0;
        }
        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }

}
