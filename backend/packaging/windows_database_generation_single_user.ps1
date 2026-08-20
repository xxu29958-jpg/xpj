#Requires -Version 5.1

param(
    [Parameter(Mandatory = $true)][string]$PostgresPath,
    [Parameter(Mandatory = $true)][string]$PhysicalPgData,
    [Parameter(Mandatory = $true)][string]$OperationId,
    [Parameter(Mandatory = $true)][string]$IntentSha256,
    [Parameter(Mandatory = $true)][string]$CandidateSha256,
    [Parameter(Mandatory = $true)][string]$CommittedRevision,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($name in @(
    "windows_installation_safety.ps1",
    "windows_database_safety.ps1",
    "windows_pg_recovery_tools.ps1",
    "windows_database_generation_contract.ps1"
)) {
    $dependency = Join-Path $root $name
    if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
        throw "database generation single-user dependency 不存在：$dependency"
    }
    . $dependency
}

$operation = ([guid]$OperationId).ToString("D")
foreach ($entry in @(
    @{ Value = $IntentSha256; Label = "intent" },
    @{ Value = $CandidateSha256; Label = "candidate" }
)) {
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$entry.Value) `
        ("single-user " + [string]$entry.Label)
}
if ($CommittedRevision -cnotmatch '^[0-9]{8}_[0-9]{4}$') {
    throw "single-user committed revision 无效。"
}
$postgres = [IO.Path]::GetFullPath($PostgresPath)
$pgData = [IO.Path]::GetFullPath($PhysicalPgData)
if (
    (Get-TicketboxPathEntryKindNoFollow $postgres) -cne "File" -or
    (Get-TicketboxPathEntryKindNoFollow $pgData) -cne "Directory"
) {
    throw "single-user PostgreSQL executable 或 PGDATA 不是可信普通路径。"
}
Assert-NoTicketboxAncestorReparsePoints $postgres
Assert-NoTicketboxAncestorReparsePoints $pgData

$retirement = ConvertTo-TicketboxDatabaseGenerationCanonicalJson ([ordered]@{
    schema = "ticketbox-database-generation-bootstrap-retirement-v1"
    operation_id = $operation
    intent_sha256 = $IntentSha256
    candidate_sha256 = $CandidateSha256
    committed_revision = $CommittedRevision
})
$literal = "'" + $retirement.Replace("'", "''") + "'"
$sql = @"
DO `$retirement`$
DECLARE observed text;
BEGIN
    SELECT pg_catalog.shobj_description(role.oid, 'pg_authid')
      INTO observed
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = 'postgres';
    IF observed IS NOT NULL AND observed <> '' AND observed <> $literal THEN
        RAISE EXCEPTION 'bootstrap retirement marker conflict';
    END IF;
END
`$retirement`$;
COMMENT ON ROLE postgres IS $literal;
ALTER ROLE postgres PASSWORD NULL;


"@
$result = Invoke-TicketboxPostgresqlHostNative `
    -FilePath $postgres `
    -Arguments @(
        "--single", "-D", $pgData, "-j", "-c", "exit_on_error=on", "ticketbox"
    ) `
    -StandardInputText $sql `
    -Label "database generation single-user bootstrap retirement" `
    -TimeoutMilliseconds $TimeoutMilliseconds
if ([int]$result.ExitCode -ne 0) {
    throw (
        "database generation single-user bootstrap retirement 失败 " +
        "(exit=$($result.ExitCode))：`n$($result.StandardError)"
    )
}
