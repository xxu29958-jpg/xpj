function TicketboxCreateFileSecure(
  FileName: String;
  DesiredAccess, ShareMode: LongWord;
  var SecurityAttributes: TTicketboxSecurityAttributes;
  CreationDisposition, FlagsAndAttributes, TemplateFile: LongWord): LongWord;
external 'CreateFileW@kernel32.dll stdcall';

function TicketboxOpenFile(
  FileName: String;
  DesiredAccess, ShareMode, SecurityAttributes, CreationDisposition,
  FlagsAndAttributes, TemplateFile: LongWord): LongWord;
external 'CreateFileW@kernel32.dll stdcall';

function TicketboxCreateDirectorySecure(
  PathName: String;
  var SecurityAttributes: TTicketboxSecurityAttributes): Boolean;
external 'CreateDirectoryW@kernel32.dll stdcall';

function TicketboxCloseHandle(Handle: LongWord): Boolean;
external 'CloseHandle@kernel32.dll stdcall';

function TicketboxGetFileInformationByHandleEx(
  Handle: LongWord;
  FileInformationClass: Integer;
  var FileInformation: TTicketboxFileAttributeTagInfo;
  BufferSize: LongWord): Boolean;
external 'GetFileInformationByHandleEx@kernel32.dll stdcall';

function TicketboxConvertSecurityDescriptor(
  StringSecurityDescriptor: String;
  StringSDRevision: LongWord;
  var SecurityDescriptor: LongWord;
  SecurityDescriptorSize: LongWord): Boolean;
external 'ConvertStringSecurityDescriptorToSecurityDescriptorW@advapi32.dll stdcall';

function TicketboxGetSecurityDescriptorOwner(
  SecurityDescriptor: LongWord;
  var Owner: LongWord;
  var OwnerDefaulted: LongWord): Boolean;
external 'GetSecurityDescriptorOwner@advapi32.dll stdcall';

function TicketboxGetSecurityDescriptorDacl(
  SecurityDescriptor: LongWord;
  var DaclPresent: LongWord;
  var Dacl: LongWord;
  var DaclDefaulted: LongWord): Boolean;
external 'GetSecurityDescriptorDacl@advapi32.dll stdcall';

function TicketboxSetSecurityInfo(
  Handle, ObjectType, SecurityInformation, Owner, Group, Dacl,
  Sacl: LongWord): LongWord;
external 'SetSecurityInfo@advapi32.dll stdcall';

function TicketboxGetSecurityInfo(
  Handle, ObjectType, SecurityInformation: LongWord;
  var Owner, Group, Dacl, Sacl, SecurityDescriptor: LongWord): LongWord;
external 'GetSecurityInfo@advapi32.dll stdcall';

function TicketboxGetSecurityDescriptorControl(
  SecurityDescriptor: LongWord;
  var Control: Word;
  var Revision: LongWord): Boolean;
external 'GetSecurityDescriptorControl@advapi32.dll stdcall';

function TicketboxEqualSid(FirstSid, SecondSid: LongWord): Boolean;
external 'EqualSid@advapi32.dll stdcall';

function TicketboxGetAclInformation(
  Acl: LongWord;
  var Information: TTicketboxAclSizeInformation;
  InformationLength, InformationClass: LongWord): Boolean;
external 'GetAclInformation@advapi32.dll stdcall';

function TicketboxCompareMemory(First, Second, Count: LongWord): Integer;
external 'memcmp@msvcrt.dll cdecl';

function TicketboxLocalFree(Memory: LongWord): LongWord;
external 'LocalFree@kernel32.dll stdcall';

function TicketboxBuildSecurityAttributes(
  const Sddl: String;
  var Descriptor: LongWord;
  var SecurityAttributes: TTicketboxSecurityAttributes): Boolean;
begin
  Result := False;
  Descriptor := 0;
  if not TicketboxConvertSecurityDescriptor(Sddl, 1, Descriptor, 0) then
    Exit;
  SecurityAttributes.nLength := SizeOf(SecurityAttributes);
  SecurityAttributes.lpSecurityDescriptor := Descriptor;
  SecurityAttributes.bInheritHandle := 0;
  Result := True;
end;

function TicketboxHandleHasExpectedType(
  Handle: LongWord;
  DirectoryRequired: Boolean): Boolean;
var
  Information: TTicketboxFileAttributeTagInfo;
  IsDirectory: Boolean;
begin
  Result := False;
  if not TicketboxGetFileInformationByHandleEx(
    Handle, 9, Information, SizeOf(Information)) then
    Exit;
  if (Information.FileAttributes and $00000400) <> 0 then
    Exit;
  IsDirectory := (Information.FileAttributes and $00000010) <> 0;
  Result := IsDirectory = DirectoryRequired;
end;

function TicketboxVerifyProtectedObject(
  Handle: LongWord;
  const ExactSddl: String): Boolean;
var
  ExpectedDescriptor, ExpectedOwner, ExpectedDacl: LongWord;
  ObservedDescriptor, ObservedOwner, ObservedGroup: LongWord;
  ObservedDacl, ObservedSacl: LongWord;
  OwnerDefaulted, DaclPresent, DaclDefaulted: LongWord;
  Control: Word;
  Revision: LongWord;
  ExpectedAcl, ObservedAcl: TTicketboxAclSizeInformation;
begin
  Result := False;
  ExpectedDescriptor := 0;
  ObservedDescriptor := 0;
  if not TicketboxConvertSecurityDescriptor(
    ExactSddl, 1, ExpectedDescriptor, 0) then
    Exit;
  try
    ExpectedOwner := 0;
    OwnerDefaulted := 0;
    if not TicketboxGetSecurityDescriptorOwner(
      ExpectedDescriptor, ExpectedOwner, OwnerDefaulted) then
      Exit;
    ExpectedDacl := 0;
    DaclPresent := 0;
    DaclDefaulted := 0;
    if not TicketboxGetSecurityDescriptorDacl(
      ExpectedDescriptor, DaclPresent, ExpectedDacl, DaclDefaulted) then
      Exit;
    if (ExpectedOwner = 0) or (DaclPresent = 0) or (ExpectedDacl = 0) then
      Exit;
    if TicketboxSetSecurityInfo(
      Handle, 1,
      TicketboxProtectedDaclSecurityInformation or $00000005,
      ExpectedOwner, 0, ExpectedDacl, 0) <> 0 then
      Exit;

    ObservedOwner := 0;
    ObservedGroup := 0;
    ObservedDacl := 0;
    ObservedSacl := 0;
    if TicketboxGetSecurityInfo(
      Handle, 1, $00000005, ObservedOwner, ObservedGroup,
      ObservedDacl, ObservedSacl, ObservedDescriptor) <> 0 then
      Exit;
    if (ObservedDescriptor = 0) or (ObservedOwner = 0) or (ObservedDacl = 0) then
      Exit;
    Control := 0;
    Revision := 0;
    if not TicketboxGetSecurityDescriptorControl(
      ObservedDescriptor, Control, Revision) then
      Exit;
    if (Control and $1000) = 0 then
      Exit;
    if not TicketboxEqualSid(ExpectedOwner, ObservedOwner) then
      Exit;
    if not TicketboxGetAclInformation(
      ExpectedDacl, ExpectedAcl, SizeOf(ExpectedAcl), 2) then
      Exit;
    if not TicketboxGetAclInformation(
      ObservedDacl, ObservedAcl, SizeOf(ObservedAcl), 2) then
      Exit;
    if (ExpectedAcl.AceCount <> ObservedAcl.AceCount) or
       (ExpectedAcl.AclBytesInUse <> ObservedAcl.AclBytesInUse) then
      Exit;
    Result := TicketboxCompareMemory(
      ExpectedDacl, ObservedDacl, ExpectedAcl.AclBytesInUse) = 0;
  finally
    if ObservedDescriptor <> 0 then
      TicketboxLocalFree(ObservedDescriptor);
    TicketboxLocalFree(ExpectedDescriptor);
  end;
end;

function TicketboxCreateProtectedFile(
  const Path, ExactSddl: String;
  var Handle: LongWord): Boolean;
var
  Descriptor: LongWord;
  SecurityAttributes: TTicketboxSecurityAttributes;
begin
  Result := False;
  Handle := $FFFFFFFF;
  if not TicketboxBuildSecurityAttributes(
    ExactSddl, Descriptor, SecurityAttributes) then
    Exit;
  try
    Handle := TicketboxCreateFileSecure(
      Path, $C00E0000, 0, SecurityAttributes, 4,
      $00000080 or TicketboxFileFlagOpenReparsePoint, 0);
  finally
    TicketboxLocalFree(Descriptor);
  end;
  if Handle = $FFFFFFFF then
    Exit;
  if not TicketboxHandleHasExpectedType(Handle, False) or
     not TicketboxVerifyProtectedObject(Handle, ExactSddl) then
  begin
    TicketboxCloseHandle(Handle);
    Handle := $FFFFFFFF;
    Exit;
  end;
  Result := True;
end;

function TicketboxCreateProtectedDirectory(
  const Path, ExactSddl: String;
  var Handle: LongWord): Boolean;
var
  Descriptor: LongWord;
  SecurityAttributes: TTicketboxSecurityAttributes;
  Created: Boolean;
  ErrorCode: LongWord;
begin
  Result := False;
  Handle := $FFFFFFFF;
  if not TicketboxBuildSecurityAttributes(
    ExactSddl, Descriptor, SecurityAttributes) then
    Exit;
  try
    Created := TicketboxCreateDirectorySecure(Path, SecurityAttributes);
    if not Created then
    begin
      ErrorCode := DLLGetLastError;
      if ErrorCode <> 183 then
        Exit;
    end;
  finally
    TicketboxLocalFree(Descriptor);
  end;
  Handle := TicketboxOpenFile(
    Path, $000E0000, 0, 0, 3,
    TicketboxFileFlagBackupSemantics or TicketboxFileFlagOpenReparsePoint, 0);
  if Handle = $FFFFFFFF then
    Exit;
  if not TicketboxHandleHasExpectedType(Handle, True) or
     not TicketboxVerifyProtectedObject(Handle, ExactSddl) then
  begin
    TicketboxCloseHandle(Handle);
    Handle := $FFFFFFFF;
    Exit;
  end;
  Result := True;
end;
