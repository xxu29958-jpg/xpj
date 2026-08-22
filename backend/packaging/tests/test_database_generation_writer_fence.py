from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
ROLE_FENCE = PACKAGING / "windows_database_generation_role_fence.ps1"


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^function {re.escape(name)}(?:\([^{{\r\n]*\))?\s*\{{",
        source,
    )
    assert match is not None, name
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unterminated PowerShell function: {name}")


def test_database_generation_writer_fence_commits_all_effective_writer_authorities(
    tmp_path: Path,
) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (
            PACKAGING / "postgresql_writer_fence" / "primitives.ps1",
            PACKAGING / "postgresql_writer_fence" / "observation_query.ps1",
            PACKAGING / "postgresql_writer_fence" / "precondition_guard.ps1",
            PACKAGING / "postgresql_writer_fence" / "session_drain.ps1",
            PACKAGING / "postgresql_writer_fence" / "reconciler.ps1",
            ROLE_FENCE,
        )
    )

    for required in (
        "pg_try_advisory_lock(",
        "SELECT pg_stat_clear_snapshot();",
        "has_database_privilege(",
        "has_schema_privilege(",
        "has_table_privilege(",
        "has_sequence_privilege(",
        "pg_has_role(",
        "current_setting('max_prepared_transactions')",
        "FROM pg_prepared_xacts",
        "FROM pg_subscription",
        "unexpected_database_worker_count",
        "can_assume_write_owner",
        "owns_security_definer_routines",
        "can_execute_unowned_security_definer_routines",
        "Get-TicketboxDatabaseGenerationFrozenFence",
        "Get-TicketboxPostgresqlWriterFenceObservation",
    ):
        assert required in source
    assert "pg_terminate_backend(\n                fence_pid," in source
    assert "$TerminationTimeoutMilliseconds" in source
    assert "database_lock.locktype = 'object'" in source
    assert "database_lock.classid = 'pg_database'::regclass::oid" in source

    frozen_fence = _function(
        ROLE_FENCE.read_text(encoding="utf-8-sig"),
        "Get-TicketboxDatabaseGenerationFrozenFence",
    )
    script = (
        r'''
$ErrorActionPreference = "Stop"
function Get-TicketboxDatabaseAuthorizationContract {
    return [pscustomobject]@{
        DatabaseName = "ticketbox"
        OwnerRole = "ticketbox_owner"
        MigratorRole = "ticketbox_migrator"
        RuntimeRole = "ticketbox_runtime"
        BackupRole = "ticketbox_backup"
    }
}
function New-TicketboxPostgresqlLocalDatabaseUrl {
    param([object]$Authority, [string]$Database, [string]$Role)
    return "postgresql://localhost/ticketbox"
}

function Invoke-TicketboxWithPlainPostgresqlSecret {
    param([Security.SecureString]$Secret, [scriptblock]$Action)
    return & $Action "fixture-secret"
}

function Get-TicketboxPostgresqlWriterFenceObservation {
    return $script:WriterFenceObservation
}

function New-TestWriterFenceObservation {
    return [pscustomobject]@{
        PublicConnect = $false
        OtherClientSessionCount = [int64]0
        ClientSessions = @()
        MaxPreparedTransactions = [int64]0
        PreparedTransactionCount = [int64]0
        LogicalSubscriptionCount = [int64]0
        LogicalApplyWorkerCount = [int64]0
        UnexpectedDatabaseWorkerCount = [int64]0
        AdvisoryFenceAvailable = $true
        AdvisoryFenceReleased = $true
        Roles = @(
            [pscustomobject]@{
                name = "ticketbox_owner"
                can_login = $false
                connection_limit = -1
                can_assume_write_owner = $false
                direct_connect = $false
                effective_connect = $false
                can_table_write = $false
                can_sequence_write = $false
            },
            [pscustomobject]@{
                name = "ticketbox_migrator"
                can_login = $true
                connection_limit = 1
                can_assume_write_owner = $true
                direct_connect = $true
                effective_connect = $true
                can_table_write = $false
                can_sequence_write = $false
            },
            [pscustomobject]@{
                name = "ticketbox_runtime"
                can_login = $false
                connection_limit = 0
                can_assume_write_owner = $false
                direct_connect = $false
                effective_connect = $false
                can_table_write = $false
                can_sequence_write = $false
            },
            [pscustomobject]@{
                name = "ticketbox_backup"
                can_login = $false
                connection_limit = 0
                can_assume_write_owner = $false
                direct_connect = $false
                effective_connect = $false
                can_table_write = $false
                can_sequence_write = $false
            },
            [pscustomobject]@{
                name = "postgres"
                can_login = $true
                is_superuser = $true
            },
            [pscustomobject]@{
                name = "inert_unregistered"
                can_login = $false
                direct_connect = $false
                effective_connect = $false
                is_superuser = $false
                can_create_db = $false
                can_create_role = $false
                can_replicate = $false
                can_bypass_rls = $false
                is_database_owner = $false
                owns_managed_schema = $false
                owns_managed_relations = $false
                owns_security_definer_routines = $false
                can_execute_unowned_security_definer_routines = $false
                can_database_create = $false
                can_managed_schema_create = $false
                can_table_write = $false
                can_sequence_write = $false
                can_assume_write_owner = $false
                predefined_role_usage = @()
                predefined_role_set = @()
            }
        )
    }
}
'''
        + frozen_fence
        + r'''

$hostAuthority = [pscustomobject]@{ PsqlPath = "psql" }
$secret = New-Object Security.SecureString
$script:WriterFenceObservation = New-TestWriterFenceObservation
Get-TicketboxDatabaseGenerationFrozenFence $hostAuthority $secret | Out-Null

$cases = @(
    [pscustomobject]@{ Name = "public-connect"; Apply = { param($o) $o.PublicConnect = $true } },
    [pscustomobject]@{ Name = "other-client"; Apply = { param($o) $o.OtherClientSessionCount = 1 } },
    [pscustomobject]@{ Name = "managed-client"; Apply = { param($o) $o.ClientSessions = @("pid") } },
    [pscustomobject]@{ Name = "prepared-enabled"; Apply = { param($o) $o.MaxPreparedTransactions = 1 } },
    [pscustomobject]@{ Name = "prepared-active"; Apply = { param($o) $o.PreparedTransactionCount = 1 } },
    [pscustomobject]@{ Name = "subscription"; Apply = { param($o) $o.LogicalSubscriptionCount = 1 } },
    [pscustomobject]@{ Name = "logical-worker"; Apply = { param($o) $o.LogicalApplyWorkerCount = 1 } },
    [pscustomobject]@{ Name = "database-worker"; Apply = { param($o) $o.UnexpectedDatabaseWorkerCount = 1 } },
    [pscustomobject]@{ Name = "advisory-unavailable"; Apply = { param($o) $o.AdvisoryFenceAvailable = $false } },
    [pscustomobject]@{ Name = "advisory-held"; Apply = { param($o) $o.AdvisoryFenceReleased = $false } },
    [pscustomobject]@{ Name = "database-authority-duplicate"; Apply = { param($o) $o.Roles = @($o.Roles) + @($o.Roles[4]) } },
    [pscustomobject]@{ Name = "database-authority-no-login"; Apply = { param($o) $o.Roles[4].can_login = $false } },
    [pscustomobject]@{ Name = "database-authority-not-superuser"; Apply = { param($o) $o.Roles[4].is_superuser = $false } },
    [pscustomobject]@{ Name = "owner-duplicate"; Apply = { param($o) $o.Roles = @($o.Roles) + @($o.Roles[0]) } },
    [pscustomobject]@{ Name = "owner-login"; Apply = { param($o) $o.Roles[0].can_login = $true } },
    [pscustomobject]@{ Name = "migrator-duplicate"; Apply = { param($o) $o.Roles = @($o.Roles) + @($o.Roles[1]) } },
    [pscustomobject]@{ Name = "migrator-no-login"; Apply = { param($o) $o.Roles[1].can_login = $false } },
    [pscustomobject]@{ Name = "migrator-unbounded"; Apply = { param($o) $o.Roles[1].connection_limit = -1 } },
    [pscustomobject]@{ Name = "migrator-no-owner"; Apply = { param($o) $o.Roles[1].can_assume_write_owner = $false } },
    [pscustomobject]@{ Name = "runtime-missing"; Apply = { param($o) $o.Roles = @($o.Roles | Where-Object { $_.name -cne "ticketbox_runtime" }) } },
    [pscustomobject]@{ Name = "runtime-login"; Apply = { param($o) $o.Roles[2].can_login = $true } },
    [pscustomobject]@{ Name = "runtime-unbounded"; Apply = { param($o) $o.Roles[2].connection_limit = -1 } },
    [pscustomobject]@{ Name = "runtime-direct-connect"; Apply = { param($o) $o.Roles[2].direct_connect = $true } },
    [pscustomobject]@{ Name = "runtime-connect"; Apply = { param($o) $o.Roles[2].effective_connect = $true } },
    [pscustomobject]@{ Name = "runtime-table-write"; Apply = { param($o) $o.Roles[2].can_table_write = $true } },
    [pscustomobject]@{ Name = "runtime-sequence-write"; Apply = { param($o) $o.Roles[2].can_sequence_write = $true } },
    [pscustomobject]@{ Name = "runtime-owner"; Apply = { param($o) $o.Roles[2].can_assume_write_owner = $true } },
    [pscustomobject]@{ Name = "backup-login"; Apply = { param($o) $o.Roles[3].can_login = $true } },
    [pscustomobject]@{ Name = "backup-unbounded"; Apply = { param($o) $o.Roles[3].connection_limit = -1 } },
    [pscustomobject]@{ Name = "backup-direct-connect"; Apply = { param($o) $o.Roles[3].direct_connect = $true } },
    [pscustomobject]@{ Name = "backup-connect"; Apply = { param($o) $o.Roles[3].effective_connect = $true } },
    [pscustomobject]@{ Name = "backup-table-write"; Apply = { param($o) $o.Roles[3].can_table_write = $true } },
    [pscustomobject]@{ Name = "backup-sequence-write"; Apply = { param($o) $o.Roles[3].can_sequence_write = $true } },
    [pscustomobject]@{ Name = "backup-owner"; Apply = { param($o) $o.Roles[3].can_assume_write_owner = $true } }
)

foreach ($property in @(
    "can_login", "direct_connect", "effective_connect", "is_superuser",
    "can_create_db", "can_create_role", "can_replicate", "can_bypass_rls",
    "is_database_owner", "owns_managed_schema", "owns_managed_relations",
    "owns_security_definer_routines",
    "can_execute_unowned_security_definer_routines", "can_database_create",
    "can_managed_schema_create", "can_table_write", "can_sequence_write",
    "can_assume_write_owner"
)) {
    $capturedProperty = $property
    $cases += [pscustomobject]@{
        Name = "unregistered-$property"
        Apply = ({
            param($o)
            $o.Roles[5].$capturedProperty = $true
        }.GetNewClosure())
    }
}
$cases += [pscustomobject]@{
    Name = "unregistered-predefined-usage"
    Apply = { param($o) $o.Roles[5].predefined_role_usage = @("pg_read_all_data") }
}
$cases += [pscustomobject]@{
    Name = "unregistered-predefined-set"
    Apply = { param($o) $o.Roles[5].predefined_role_set = @("pg_write_all_data") }
}

foreach ($case in $cases) {
    $script:WriterFenceObservation = New-TestWriterFenceObservation
    & $case.Apply $script:WriterFenceObservation
    $rejected = $false
    try {
        Get-TicketboxDatabaseGenerationFrozenFence $hostAuthority $secret | Out-Null
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw "unsafe writer-fence observation was accepted: $($case.Name)"
    }
}
'''
    )
    path = tmp_path / "database-generation-writer-fence.ps1"
    path.write_text(script, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
