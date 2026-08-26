function TicketboxResultDirectory: String;
begin
  Result := ExpandConstant('{commoncf64}\Ticketbox\setup-result');
end;

function TicketboxResultPath: String;
begin
  Result := TicketboxResultDirectory + '\ticketbox-install-result.json';
end;

function TicketboxPreparePrivateResult(var Failure: String): Boolean;
var
  Handle: LongWord;
begin
  Result := False;
  Failure := '';
  if TicketboxResultDirectoryHandle <> 0 then
  begin
    Result := True;
    Exit;
  end;
  if not TicketboxCreateProtectedDirectory(
    TicketboxResultDirectory,
    'O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)',
    Handle) then
  begin
    Failure := '无法创建受保护的首次配对结果目录';
    Exit;
  end;
  TicketboxResultDirectoryHandle := Handle;
  if FileExists(TicketboxResultPath) and
     (not DeleteFile(TicketboxResultPath)) then
  begin
    Failure := '无法清理上一次受保护的首次配对结果';
    Exit;
  end;
  Result := True;
end;

procedure TicketboxDeletePrivateResult;
begin
  if FileExists(TicketboxResultPath) then
    DeleteFile(TicketboxResultPath);
end;

procedure TicketboxReleasePrivateResult;
begin
  TicketboxDeletePrivateResult;
  if TicketboxResultDirectoryHandle <> 0 then
  begin
    TicketboxCloseHandle(TicketboxResultDirectoryHandle);
    TicketboxResultDirectoryHandle := 0;
  end;
  RemoveDir(TicketboxResultDirectory);
end;
