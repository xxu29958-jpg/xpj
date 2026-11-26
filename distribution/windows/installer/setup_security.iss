function TicketboxGetFileAttributes(FileName: String): LongWord;
external 'GetFileAttributesW@kernel32.dll stdcall';

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

function TicketboxLocalAlloc(uFlags, uBytes: LongWord): LongWord;
external 'LocalAlloc@kernel32.dll stdcall';

function TicketboxLocalFree(Memory: LongWord): LongWord;
external 'LocalFree@kernel32.dll stdcall';

function TicketboxFindFirstFile(FileName: String; FindData: LongWord): LongWord;
external 'FindFirstFileW@kernel32.dll stdcall';

function TicketboxFindNextFile(Handle, FindData: LongWord): LongBool;
external 'FindNextFileW@kernel32.dll stdcall';

function TicketboxFindClose(Handle: LongWord): LongBool;
external 'FindClose@kernel32.dll stdcall';

function TicketboxWideStrLen(StrPtr: LongWord): Integer;
external 'lstrlenW@kernel32.dll stdcall';

function TicketboxCopyWideStr(
  Dest: String;
  SrcPtr: LongWord;
  MaxChars: Integer): LongWord;
external 'lstrcpynW@kernel32.dll stdcall';

function TicketboxReadFindEntryName(FindData: LongWord; var OutName: String): Boolean;
var
  NamePtr: LongWord;
  Len: Integer;
begin
  Result := False;
  OutName := '';
  if FindData = 0 then
    Exit;
  NamePtr := FindData + 44;
  Len := TicketboxWideStrLen(NamePtr);
  if (Len <= 0) or (Len > 259) then
    Exit;
  SetLength(OutName, Len + 1);
  if TicketboxCopyWideStr(OutName, NamePtr, Len + 1) = 0 then
    Exit;
  SetLength(OutName, Len);
  Result := True;
end;

function TicketboxConvertSecurityDescriptorToString(
  SecurityDescriptor: LongWord;
  RequestedStringSDRevision, SecurityInformation: LongWord;
  var StringSecurityDescriptor: LongWord;
  StringSecurityDescriptorLen: LongWord): Boolean;
external 'ConvertSecurityDescriptorToStringSecurityDescriptorW@advapi32.dll stdcall';

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
    Path, $000E0080, 0, 0, 3,
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

function TicketboxPathExists(const Path: String): Boolean;
var
  Attributes, ErrorCode: LongWord;
begin
  Attributes := TicketboxGetFileAttributes(Path);
  if Attributes <> $FFFFFFFF then
  begin
    Result := True;
    Exit;
  end;
  ErrorCode := DLLGetLastError;
  Result := (ErrorCode <> 2) and (ErrorCode <> 3);
end;

function TicketboxPathIsNonReparseType(
  const Path: String;
  DirectoryRequired: Boolean): Boolean;
var
  Handle: LongWord;
begin
  Result := False;
  Handle := TicketboxOpenFile(
    Path, $00000080, $00000007, 0, 3,
    TicketboxFileFlagBackupSemantics or TicketboxFileFlagOpenReparsePoint, 0);
  if Handle = $FFFFFFFF then
    Exit;
  try
    Result := TicketboxHandleHasExpectedType(Handle, DirectoryRequired);
  finally
    TicketboxCloseHandle(Handle);
  end;
end;

function TicketboxOwnerMatchesSddl(
  ObservedOwner: LongWord;
  const OwnerSddl: String): Boolean;
var
  Descriptor, ExpectedOwner, OwnerDefaulted: LongWord;
begin
  Result := False;
  Descriptor := 0;
  if not TicketboxConvertSecurityDescriptor(OwnerSddl, 1, Descriptor, 0) then
    Exit;
  try
    ExpectedOwner := 0;
    OwnerDefaulted := 0;
    if TicketboxGetSecurityDescriptorOwner(
      Descriptor, ExpectedOwner, OwnerDefaulted) and (ExpectedOwner <> 0) then
      Result := TicketboxEqualSid(ExpectedOwner, ObservedOwner);
  finally
    TicketboxLocalFree(Descriptor);
  end;
end;

function TicketboxDescriptorDaclSddl(
  Descriptor: LongWord;
  var OutSddl: String): Boolean;
var
  SddlPtr: LongWord;
  Len: Integer;
begin
  Result := False;
  OutSddl := '';
  SddlPtr := 0;
  if (not TicketboxConvertSecurityDescriptorToString(
        Descriptor, 1, $00000004, SddlPtr, 0)) or (SddlPtr = 0) then
    Exit;
  try
    Len := TicketboxWideStrLen(SddlPtr);
    if (Len <= 0) or (Len > 4096) then
      Exit;
    SetLength(OutSddl, Len + 1);
    if TicketboxCopyWideStr(OutSddl, SddlPtr, Len + 1) = 0 then
      Exit;
    SetLength(OutSddl, Len);
    Result := True;
  finally
    TicketboxLocalFree(SddlPtr);
  end;
end;

function TicketboxCanonicalDaclSddl(
  const PolicySddl: String;
  var OutSddl: String): Boolean;
var
  Descriptor: LongWord;
begin
  Result := False;
  OutSddl := '';
  Descriptor := 0;
  if not TicketboxConvertSecurityDescriptor(PolicySddl, 1, Descriptor, 0) then
    Exit;
  try
    Result := TicketboxDescriptorDaclSddl(Descriptor, OutSddl);
  finally
    TicketboxLocalFree(Descriptor);
  end;
end;

function TicketboxVerifyReadOnlyAdminDirectory(const Path: String): Boolean;
var
  Handle, ObservedDescriptor, ObservedOwner, ObservedGroup: LongWord;
  ObservedDacl, ObservedSacl: LongWord;
  ObservedSddl, SddlP, SddlPai: String;
begin
  Result := False;
  if (not TicketboxCanonicalDaclSddl('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', SddlP)) or
     (not TicketboxCanonicalDaclSddl('D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', SddlPai)) then
    Exit;
  Handle := TicketboxOpenFile(
    Path, $00020080, $00000007, 0, 3,
    TicketboxFileFlagBackupSemantics or TicketboxFileFlagOpenReparsePoint, 0);
  if Handle = $FFFFFFFF then
    Exit;
  ObservedDescriptor := 0;
  try
    if not TicketboxHandleHasExpectedType(Handle, True) then
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
    if (not TicketboxOwnerMatchesSddl(ObservedOwner, 'O:SY')) and
       (not TicketboxOwnerMatchesSddl(ObservedOwner, 'O:BA')) then
      Exit;
    if not TicketboxDescriptorDaclSddl(ObservedDescriptor, ObservedSddl) then
      Exit;
    Result := (CompareStr(ObservedSddl, SddlP) = 0) or
      (CompareStr(ObservedSddl, SddlPai) = 0);
  finally
    if ObservedDescriptor <> 0 then
      TicketboxLocalFree(ObservedDescriptor);
    TicketboxCloseHandle(Handle);
  end;
end;

function TicketboxPathAbsentOrAdminProtectedDir(const Path: String): Boolean;
begin
  if not TicketboxPathExists(Path) then
  begin
    Result := True;
    Exit;
  end;
  Result := TicketboxVerifyReadOnlyAdminDirectory(Path);
end;

function TicketboxAceIsAdminWriteOnly(const AceBody: String): Boolean;
var
  Rest, AceType, Rights, Trustee: String;
  FieldIdx, Sep: Integer;
begin
  Result := False;
  AceType := '';
  Rights := '';
  Trustee := '';
  Rest := AceBody;
  for FieldIdx := 1 to 6 do
  begin
    Sep := Pos(';', Rest);
    if FieldIdx < 6 then
    begin
      if Sep = 0 then
        Exit;
      if FieldIdx = 1 then
        AceType := UpperCase(Copy(Rest, 1, Sep - 1))
      else if FieldIdx = 3 then
        Rights := UpperCase(Copy(Rest, 1, Sep - 1));
      Delete(Rest, 1, Sep);
    end
    else
    begin
      if Sep <> 0 then
        Exit;
      Trustee := UpperCase(Rest);
    end;
  end;
  if (AceType = '') or (Trustee = '') then
    Exit;
  if AceType <> 'A' then
  begin
    Result := AceType = 'D';
    Exit;
  end;
  if (Trustee = 'SY') or (Trustee = 'BA') or (Trustee = 'CO') or
     (Trustee = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464') then
  begin
    Result := True;
    Exit;
  end;
  Result := (Rights = '0X1200A9') or (Rights = '0X120089') or
    (Rights = 'GXGR') or (Rights = 'GRGX') or
    (Rights = 'FRFX') or (Rights = 'FXFR') or
    (Rights = 'GR') or (Rights = 'FR') or (Rights = 'RC') or
    (Rights = 'GX') or (Rights = 'FX');
end;

function TicketboxDaclSddlIsAdminWriteOnly(const DaclSddl: String): Boolean;
var
  Rest, AceBody: String;
  OpenPos, ClosePos, AceCount: Integer;
begin
  Result := False;
  Rest := DaclSddl;
  AceCount := 0;
  OpenPos := Pos('(', Rest);
  while OpenPos > 0 do
  begin
    Delete(Rest, 1, OpenPos);
    ClosePos := Pos(')', Rest);
    if ClosePos <= 1 then
      Exit;
    AceBody := Copy(Rest, 1, ClosePos - 1);
    if not TicketboxAceIsAdminWriteOnly(AceBody) then
      Exit;
    AceCount := AceCount + 1;
    Delete(Rest, 1, ClosePos);
    OpenPos := Pos('(', Rest);
  end;
  Result := AceCount > 0;
end;

function TicketboxVerifyAdminWriteOnlyDirectory(const Path: String): Boolean;
var
  Handle, ObservedDescriptor, ObservedOwner, ObservedGroup: LongWord;
  ObservedDacl, ObservedSacl: LongWord;
  ObservedSddl: String;
begin
  Result := False;
  Handle := TicketboxOpenFile(
    Path, $00020080, $00000007, 0, 3,
    TicketboxFileFlagBackupSemantics or TicketboxFileFlagOpenReparsePoint, 0);
  if Handle = $FFFFFFFF then
    Exit;
  ObservedDescriptor := 0;
  try
    if not TicketboxHandleHasExpectedType(Handle, True) then
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
    if (not TicketboxOwnerMatchesSddl(ObservedOwner, 'O:SY')) and
       (not TicketboxOwnerMatchesSddl(ObservedOwner, 'O:BA')) then
      Exit;
    if not TicketboxDescriptorDaclSddl(ObservedDescriptor, ObservedSddl) then
      Exit;
    Result := TicketboxDaclSddlIsAdminWriteOnly(ObservedSddl);
  finally
    if ObservedDescriptor <> 0 then
      TicketboxLocalFree(ObservedDescriptor);
    TicketboxCloseHandle(Handle);
  end;
end;

function TicketboxPathAbsentOrAdminWriteOnlyDir(const Path: String): Boolean;
begin
  if not TicketboxPathExists(Path) then
  begin
    Result := True;
    Exit;
  end;
  Result := TicketboxVerifyAdminWriteOnlyDirectory(Path);
end;
