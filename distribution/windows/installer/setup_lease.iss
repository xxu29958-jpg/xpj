function TicketboxCreateFile(
  FileName: String;
  DesiredAccess, ShareMode, SecurityAttributes, CreationDisposition,
  FlagsAndAttributes, TemplateFile: LongWord): LongWord;
external 'CreateFileW@kernel32.dll stdcall';

function TicketboxCloseHandle(Handle: LongWord): Boolean;
external 'CloseHandle@kernel32.dll stdcall';

function TicketboxGetFileAttributes(FileName: String): LongWord;
external 'GetFileAttributesW@kernel32.dll stdcall';

function TicketboxConvertSecurityDescriptor(
  StringSecurityDescriptor: String;
  StringSDRevision: LongWord;
  var SecurityDescriptor: LongWord;
  SecurityDescriptorSize: LongWord): Boolean;
external 'ConvertStringSecurityDescriptorToSecurityDescriptorW@advapi32.dll stdcall';

function TicketboxSetKernelObjectSecurity(
  Handle: LongWord;
  SecurityInformation, SecurityDescriptor: LongWord): Boolean;
external 'SetKernelObjectSecurity@advapi32.dll stdcall';

function TicketboxLocalFree(Memory: LongWord): LongWord;
external 'LocalFree@kernel32.dll stdcall';

function TicketboxLeasePath: String;
begin
  Result := ExpandConstant('{commoncf64}\Ticketbox\setup.lock');
end;

function TicketboxProtectLeaseFile(Handle: LongWord): Boolean;
var
  Descriptor: LongWord;
begin
  Result := False;
  Descriptor := 0;
  if not TicketboxConvertSecurityDescriptor(
    'O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)', 1, Descriptor, 0) then
    Exit;
  try
    Result := TicketboxSetKernelObjectSecurity(Handle, $00000005, Descriptor);
  finally
    TicketboxLocalFree(Descriptor);
  end;
end;

function TicketboxAcquireSetupLease(var Failure: String): Boolean;
var
  LockDirectory, LockPath: String;
  Attributes, Handle, ErrorCode: LongWord;
begin
  Result := False;
  Failure := '';
  if TicketboxSetupLeaseHandle <> 0 then
  begin
    Result := True;
    Exit;
  end;
  LockDirectory := ExpandConstant('{commoncf64}\Ticketbox');
  if not ForceDirectories(LockDirectory) then
  begin
    Failure := '无法创建受保护的安装协调目录';
    Exit;
  end;
  Attributes := TicketboxGetFileAttributes(LockDirectory);
  if (Attributes = $FFFFFFFF) or
     ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) then
  begin
    Failure := '安装协调目录不是可信本地目录';
    Exit;
  end;
  LockPath := TicketboxLeasePath;
  Handle := TicketboxCreateFile(
    LockPath,
    $C00C0000,
    0,
    0,
    4,
    $00000080 or TicketboxFileFlagOpenReparsePoint,
    0);
  if Handle = $FFFFFFFF then
  begin
    ErrorCode := DLLGetLastError;
    if (ErrorCode = 32) or (ErrorCode = 33) then
      Failure := '另一个小票夹安装程序正在运行'
    else
      Failure := '无法取得安装协调租约（Windows 错误 ' +
        IntToStr(ErrorCode) + '）';
    Exit;
  end;
  if not TicketboxProtectLeaseFile(Handle) then
  begin
    TicketboxCloseHandle(Handle);
    Failure := '无法保护安装协调租约';
    Exit;
  end;
  Attributes := TicketboxGetFileAttributes(LockPath);
  if (Attributes = $FFFFFFFF) or
     ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) then
  begin
    TicketboxCloseHandle(Handle);
    Failure := '安装协调租约不是可信普通文件';
    Exit;
  end;
  TicketboxSetupLeaseHandle := Handle;
  Result := True;
end;

procedure TicketboxReleaseSetupLease;
var
  LockPath: String;
begin
  if TicketboxSetupLeaseHandle = 0 then
    Exit;
  LockPath := TicketboxLeasePath;
  TicketboxCloseHandle(TicketboxSetupLeaseHandle);
  TicketboxSetupLeaseHandle := 0;
  DeleteFile(LockPath);
end;
