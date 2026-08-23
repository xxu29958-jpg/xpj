from __future__ import annotations

import copy
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
LOADER = PACKAGING / "windows_postgresql_writer_fence.ps1"
COMPONENTS = (
    PACKAGING / "postgresql_writer_fence" / "primitives.ps1",
    PACKAGING / "postgresql_writer_fence" / "observation_query.ps1",
    PACKAGING / "postgresql_writer_fence" / "observation_codec.ps1",
    PACKAGING / "postgresql_writer_fence" / "observation.ps1",
    PACKAGING / "postgresql_writer_fence" / "reconcile_policy.ps1",
    PACKAGING / "postgresql_writer_fence" / "precondition_guard.ps1",
    PACKAGING / "postgresql_writer_fence" / "session_drain.ps1",
    PACKAGING / "postgresql_writer_fence" / "reconciler.ps1",
)
INSTALLATION_SAFETY = PACKAGING / "windows_installation_safety.ps1"
INNO = PACKAGING / "ticketbox-installer.iss"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"

SHIPMENT = (
    (
        r"windows_postgresql_writer_fence.ps1",
        r"{app}\installer",
        "PostgresqlWriterFenceScript",
        r"packaging\windows_postgresql_writer_fence.ps1",
    ),
    *(
        (
            rf"postgresql_writer_fence\{name}.ps1",
            r"{app}\installer\postgresql_writer_fence",
            variable,
            rf"packaging\postgresql_writer_fence\{name}.ps1",
        )
        for name, variable in (
            ("primitives", "PostgresqlWriterFencePrimitivesScript"),
            ("observation_query", "PostgresqlWriterFenceObservationQueryScript"),
            ("observation_codec", "PostgresqlWriterFenceObservationCodecScript"),
            ("observation", "PostgresqlWriterFenceObservationScript"),
            ("reconcile_policy", "PostgresqlWriterFenceReconcilePolicyScript"),
            (
                "precondition_guard",
                "PostgresqlWriterFencePreconditionGuardScript",
            ),
            ("session_drain", "PostgresqlWriterFenceSessionDrainScript"),
            ("reconciler", "PostgresqlWriterFenceReconcilerScript"),
        )
    ),
)


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _run(engine: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
    )


def _without_block_comments(source: str) -> str:
    return re.sub(r"<#.*?#>", "", source, flags=re.DOTALL)


def _load_generic() -> str:
    return (
        f". '{_literal(INSTALLATION_SAFETY)}'\n"
        f". '{_literal(LOADER)}'"
    )


def _observation_payload() -> dict[str, object]:
    authority = {
        "name": "db_authority",
        "oid": 10,
        "can_login": True,
        "connection_limit": -1,
        "is_superuser": True,
        "can_create_db": True,
        "can_create_role": True,
        "can_replicate": True,
        "can_bypass_rls": True,
        "is_database_owner": True,
        "owns_managed_schema": True,
        "owns_managed_relations": True,
        "owns_security_definer_routines": False,
        "can_execute_unowned_security_definer_routines": False,
        "direct_connect": True,
        "effective_connect": True,
        "can_database_create": True,
        "can_managed_schema_create": True,
        "can_table_write": True,
        "can_sequence_write": True,
        "can_assume_write_owner": False,
        "predefined_role_usage": ["pg_database_owner"],
        "predefined_role_set": [],
    }
    runtime = {
        "name": "app_runtime",
        "oid": 11,
        "can_login": True,
        "connection_limit": -1,
        "is_superuser": False,
        "can_create_db": False,
        "can_create_role": False,
        "can_replicate": False,
        "can_bypass_rls": False,
        "is_database_owner": False,
        "owns_managed_schema": False,
        "owns_managed_relations": False,
        "owns_security_definer_routines": False,
        "can_execute_unowned_security_definer_routines": False,
        "direct_connect": True,
        "effective_connect": True,
        "can_database_create": False,
        "can_managed_schema_create": False,
        "can_table_write": True,
        "can_sequence_write": True,
        "can_assume_write_owner": False,
        "predefined_role_usage": [],
        "predefined_role_set": [],
    }
    return {
        "public_connect": True,
        "client_session_count": 1,
        "client_sessions": [
            {
                "pid": 7012,
                "role": "app_runtime",
                "application_name": "contract-writer",
                "state": "idle",
            }
        ],
        "max_prepared_transactions": 0,
        "prepared_transaction_count": 0,
        "logical_subscription_count": 0,
        "logical_apply_worker_count": 0,
        "unexpected_database_worker_count": 0,
        "advisory_available": True,
        "advisory_released": True,
        "roles": [authority, runtime],
    }


def test_writer_fence_has_small_c07_free_components() -> None:
    loader = LOADER.read_text(encoding="utf-8-sig")
    sources = [path.read_text(encoding="utf-8-sig") for path in COMPONENTS]
    generic = loader + "\n" + "\n".join(sources)

    for path in (LOADER, *COMPONENTS):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert all(len(source.splitlines()) <= 360 for source in sources)
    for forbidden in (
        "C07",
        "c07",
        "ticketbox-c07",
        "xiaopiaojia:schema",
        "TicketboxC07",
        "ticketbox_runtime",
        "ticketbox_migrator",
    ):
        assert forbidden not in generic

    for required in (
        "Get-TicketboxPostgresqlWriterFenceObservation",
        "Invoke-TicketboxPostgresqlWriterFenceReconcile",
        "pg_try_advisory_lock(",
        "pg_advisory_unlock(",
        "pg_terminate_backend(",
        "pg_stat_clear_snapshot",
        "activity.usename = ANY($ManagedRolesSql)",
        "database_lock.mode = 'RowExclusiveLock'",
        "ALTER ROLE %I NOLOGIN CONNECTION LIMIT 0",
        "REVOKE CONNECT ON DATABASE %I FROM %I",
        "has_any_column_privilege(",
        "FROM information_schema.views AS view_capability",
    ):
        assert required in generic
def test_writer_fence_is_actively_shipped_and_provenance_bound() -> None:
    active_inno_lines = {
        line.strip()
        for line in INNO.read_text(encoding="utf-8-sig").splitlines()
        if line.lstrip().startswith("Source:")
    }
    active_build = _without_block_comments(BUILD.read_text(encoding="utf-8-sig"))
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    recipe_start = provenance.index(
        "$script:TicketboxInstallerRecipeRelativePaths = @(")
    recipe = provenance[
        recipe_start : provenance.index("\n)\n", recipe_start)
    ]
    for source, destination, variable, recipe_path in SHIPMENT:
        assert (
            f'Source: "{source}"; DestDir: "{destination}"; '
            "Flags: ignoreversion; Check: AuthoritativePayloadReplacementPrepared"
        ) in active_inno_lines
        assert re.search(
            rf'Assert-File\s+`\s*\${variable}\s+`\s*"[^"]+"',
            active_build,
        )
        assert f'"{recipe_path}",' in recipe


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_writer_fence_loaders_guard_every_component(engine: str) -> None:
    all_components = COMPONENTS
    expected = ",".join(path.name for path in all_components)
    script = f"""
$ErrorActionPreference = 'Stop'
$script:ancestor = @()
$script:kind = @()
function Assert-NoTicketboxAncestorReparsePoints {{
    param([string]$Path)
    $script:ancestor += [IO.Path]::GetFileName($Path)
}}
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    $script:kind += [IO.Path]::GetFileName($Path)
    'File'
}}
. '{_literal(LOADER)}'
if ([string]::Join(',', $script:ancestor) -cne '{expected}') {{
    throw 'writer-fence ancestor guard coverage drifted'
}}
if ([string]::Join(',', $script:kind) -cne '{expected}') {{
    throw 'writer-fence no-follow guard coverage drifted'
}}
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ([IO.Path]::GetFileName($Path) -ceq 'reconciler.ps1') {{
        return 'ReparsePoint'
    }}
    'File'
}}
$rejected = $false
try {{ . '{_literal(LOADER)}' }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'generic reparse component was loaded' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_writer_fence_observation_is_typed_and_parameterized(engine: str) -> None:
    payload = {
        "public_connect": True,
        "client_session_count": 1,
        "client_sessions": [
            {
                "pid": 7012,
                "role": "app_runtime",
                "application_name": "contract-writer",
                "state": "idle",
            }
        ],
        "max_prepared_transactions": 0,
        "prepared_transaction_count": 0,
        "logical_subscription_count": 0,
        "logical_apply_worker_count": 0,
        "unexpected_database_worker_count": 0,
        "advisory_available": True,
        "advisory_released": True,
        "roles": [
            {
                "name": "db_authority",
                "oid": 10,
                "can_login": True,
                "connection_limit": -1,
                "is_superuser": True,
                "can_create_db": True,
                "can_create_role": True,
                "can_replicate": True,
                "can_bypass_rls": True,
                "is_database_owner": True,
                "owns_managed_schema": True,
                "owns_managed_relations": True,
                "owns_security_definer_routines": False,
                "can_execute_unowned_security_definer_routines": False,
                "direct_connect": True,
                "effective_connect": True,
                "can_database_create": True,
                "can_managed_schema_create": True,
                "can_table_write": True,
                "can_sequence_write": True,
                "can_assume_write_owner": False,
                "predefined_role_usage": ["pg_database_owner"],
                "predefined_role_set": [],
            },
            {
                "name": "app_runtime",
                "oid": 11,
                "can_login": True,
                "connection_limit": -1,
                "is_superuser": False,
                "can_create_db": False,
                "can_create_role": False,
                "can_replicate": False,
                "can_bypass_rls": False,
                "is_database_owner": False,
                "owns_managed_schema": False,
                "owns_managed_relations": False,
                "owns_security_definer_routines": False,
                "can_execute_unowned_security_definer_routines": False,
                "direct_connect": True,
                "effective_connect": True,
                "can_database_create": False,
                "can_managed_schema_create": False,
                "can_table_write": True,
                "can_sequence_write": True,
                "can_assume_write_owner": False,
                "predefined_role_usage": [],
                "predefined_role_set": [],
            },
        ],
    }
    payload_json = json.dumps(payload, separators=(",", ":")).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    param($PsqlPath, $DatabaseUrl, $Password, $Sql, $Label, $TimeoutMilliseconds)
    if ($Sql -notmatch [regex]::Escape("hashtext('lease-label')")) {{
        throw 'lease label was not parameterized'
    }}
    if ($Sql -notmatch "nspname = 'managed_schema'") {{
        throw 'managed schema was not parameterized'
    }}
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = '{payload_json}'
    }}
}}
    {_load_generic()}
$observation = Get-TicketboxPostgresqlWriterFenceObservation `
    -PsqlPath 'C:\\pg\\psql.exe' `
    -DatabaseUrl 'postgresql://db_authority@127.0.0.1:5432/app' `
    -Password 'secret' `
    -ManagedSchemaName 'managed_schema' `
    -AdvisoryLockLabel 'lease-label' `
    -ApplicationName 'contract-observer' `
    -TimeoutMilliseconds 5000 `
    -StatementTimeoutMilliseconds 3000 `
    -LockTimeoutMilliseconds 500
if ($observation.Roles.Count -ne 2) {{ throw 'role count mismatch' }}
if ($observation.ClientSessions[0].role -cne 'app_runtime') {{
    throw 'session role mismatch'
}}
if (-not $observation.AdvisoryFenceReleased) {{ throw 'release evidence missing' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_writer_fence_observation_rejects_untyped_or_ambiguous_evidence(
    engine: str,
) -> None:
    bad_payloads: list[tuple[str, dict[str, object]]] = []

    def add_case(
        label: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> None:
        payload = copy.deepcopy(_observation_payload())
        mutate(payload)
        bad_payloads.append((label, payload))

    add_case("string count", lambda item: item.__setitem__("client_session_count", "1"))
    add_case(
        "string pid",
        lambda item: item["client_sessions"][0].__setitem__("pid", "7012"),
    )
    add_case(
        "unknown session state",
        lambda item: item["client_sessions"][0].__setitem__("state", "waiting"),
    )
    add_case(
        "string connection limit",
        lambda item: item["roles"][1].__setitem__("connection_limit", "-1"),
    )
    add_case(
        "numeric boolean",
        lambda item: item["roles"][1].__setitem__("can_login", 1),
    )
    add_case(
        "duplicate role oid",
        lambda item: item["roles"][1].__setitem__("oid", 10),
    )
    add_case("unknown top-level field", lambda item: item.__setitem__("extra", 1))

    cases = ",\n".join(
        "[pscustomobject]@{ Label = '"
        + label.replace("'", "''")
        + "'; Json = '"
        + json.dumps(payload, separators=(",", ":")).replace("'", "''")
        + "' }"
        for label, payload in bad_payloads
    )
    valid = json.dumps(_observation_payload(), separators=(",", ":")).replace(
        "'", "''"
    )
    script = f"""
$ErrorActionPreference = 'Stop'
    {_load_generic()}
[void](ConvertFrom-TicketboxPostgresqlWriterFenceObservationJson '{valid}')
$cases = @(
{cases}
)
foreach ($case in $cases) {{
    $rejected = $false
    try {{
        [void](
            ConvertFrom-TicketboxPostgresqlWriterFenceObservationJson `
                ([string]$case.Json)
        )
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "accepted bad evidence: $($case.Label)" }}
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_writer_fence_reconcile_uses_explicit_policy_inputs(engine: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    param($PsqlPath, $DatabaseUrl, $Password, $Sql, $Label, $TimeoutMilliseconds)
    foreach ($required in @(
        "ARRAY['app_runtime']::text[]",
        "ARRAY['db_authority', 'app_migrator', 'app_owner', 'app_runtime']::text[]",
        "ARRAY['db_authority', 'app_migrator']::text[]",
        "ARRAY['app_owner']::text[]",
        "ARRAY['app_migrator']::text[]",
        "hashtext('lease-label')",
        "nspname = 'managed_schema'",
        "session_user <> 'db_authority'",
        'pg_terminate_backend(',
        'Authorized non-writer role has unexpected LOGIN',
        "AND usename <> ALL(ARRAY['app_runtime']::text[])",
        'has_database_privilege(',
        "predefined.rolname ~ '^pg_'",
        "pg_has_role(role.oid, predefined.oid, 'SET')",
        "routine.prosecdef",
        "has_function_privilege(role.oid, routine.oid, 'EXECUTE')",
        "has_schema_privilege(role.oid, namespace.oid, 'USAGE')",
        "namespace.nspname <> 'information_schema'",
        "namespace.nspname !~ '^pg_'",
        "SECURITY DEFINER routine owner is outside the allowed authority policy"
    )) {{
        if (-not $Sql.Contains($required)) {{ throw "missing SQL contract: $required" }}
    }}
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = '{{"advisory_released":true}}'
    }}
}}
    {_load_generic()}
$result = Invoke-TicketboxPostgresqlWriterFenceReconcile `
    -PsqlPath 'C:\\pg\\psql.exe' `
    -DatabaseUrl 'postgresql://db_authority@127.0.0.1:5432/app' `
    -Password 'secret' `
    -AuthorityRole 'db_authority' `
    -ManagedSchemaName 'managed_schema' `
    -AdvisoryLockLabel 'lease-label' `
    -ApplicationName 'contract-fence' `
    -ManagedWriterRoles @('app_runtime') `
    -AuthorizedRoleNames @('db_authority', 'app_migrator', 'app_owner', 'app_runtime') `
        -AllowedLoginRolesAfterFence @('db_authority', 'app_migrator') `
        -AllowedDatabaseOwnerRoles @('app_owner') `
        -AllowedManagedWriterOwnerRoles @() `
        -AllowedDatabaseOwnerTransitionRoles @('app_migrator') `
    -TimeoutMilliseconds 5000 `
    -LockTimeoutMilliseconds 500 `
    -TerminationTimeoutMilliseconds 2000
if (-not $result.AdvisoryFenceReleased) {{ throw 'release evidence missing' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_writer_fence_reconcile_rejects_each_invalid_policy_before_sql(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$script:sqlCalls = 0
$script:resultJson = '{{"advisory_released":true}}'
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    param($PsqlPath, $DatabaseUrl, $Password, $Sql, $Label, $TimeoutMilliseconds)
    $script:sqlCalls += 1
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = $script:resultJson
    }}
}}
    {_load_generic()}
$base = @{{
    PsqlPath = 'C:\\pg\\psql.exe'
    DatabaseUrl = 'postgresql://db_authority@127.0.0.1:5432/app'
    Password = 'secret'
    AuthorityRole = 'db_authority'
    ManagedSchemaName = 'managed_schema'
    AdvisoryLockLabel = 'lease-label'
    ApplicationName = 'contract-fence'
    ManagedWriterRoles = @('app_runtime')
    AuthorizedRoleNames = @(
        'db_authority', 'app_migrator', 'app_owner', 'app_runtime'
    )
    AllowedLoginRolesAfterFence = @('db_authority', 'app_migrator')
    AllowedDatabaseOwnerRoles = @('app_owner')
    AllowedManagedWriterOwnerRoles = @()
    AllowedDatabaseOwnerTransitionRoles = @('app_migrator')
    TimeoutMilliseconds = 5000
    LockTimeoutMilliseconds = 500
    TerminationTimeoutMilliseconds = 2000
}}
function Assert-PolicyRejected([string]$Label, [hashtable]$Changes) {{
    $parameters = @{{}}
    foreach ($key in $base.Keys) {{ $parameters[$key] = $base[$key] }}
    foreach ($key in $Changes.Keys) {{ $parameters[$key] = $Changes[$key] }}
    $before = $script:sqlCalls
    $rejected = $false
    try {{ [void](Invoke-TicketboxPostgresqlWriterFenceReconcile @parameters) }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "accepted invalid policy: $Label" }}
    if ($script:sqlCalls -ne $before) {{
        throw "invalid policy reached SQL: $Label"
    }}
}}
Assert-PolicyRejected 'authority absent' @{{
    AuthorizedRoleNames = @('app_migrator', 'app_owner', 'app_runtime')
}}
Assert-PolicyRejected 'managed role allowed login' @{{
    AllowedLoginRolesAfterFence = @(
        'db_authority', 'app_migrator', 'app_runtime'
    )
}}
Assert-PolicyRejected 'managed role not authorized' @{{
    ManagedWriterRoles = @('foreign_runtime')
}}
Assert-PolicyRejected 'allowed login not authorized' @{{
    AllowedLoginRolesAfterFence = @('db_authority', 'foreign_login')
}}
Assert-PolicyRejected 'database owner absent' @{{
    AllowedDatabaseOwnerRoles = @()
}}
Assert-PolicyRejected 'database owner not authorized' @{{
    AllowedDatabaseOwnerRoles = @('foreign_owner')
}}
Assert-PolicyRejected 'database owner transition not authorized' @{{
    AllowedDatabaseOwnerTransitionRoles = @('foreign_migrator')
}}
Assert-PolicyRejected 'database owner transition cannot login after fence' @{{
    AllowedDatabaseOwnerTransitionRoles = @('app_owner')
}}
Assert-PolicyRejected 'managed writer cannot transition to owner' @{{
    AllowedDatabaseOwnerTransitionRoles = @('app_runtime')
}}
Assert-PolicyRejected 'managed owner not allowed owner' @{{
    AllowedManagedWriterOwnerRoles = @('app_runtime')
}}
Assert-PolicyRejected 'duplicate managed role' @{{
    ManagedWriterRoles = @('app_runtime', 'app_runtime')
}}
Assert-PolicyRejected 'invalid role identifier' @{{
    ManagedWriterRoles = @('App-Runtime')
}}
Assert-PolicyRejected 'lock timeout widens native deadline' @{{
    LockTimeoutMilliseconds = 6000
}}
Assert-PolicyRejected 'termination timeout widens native deadline' @{{
    TerminationTimeoutMilliseconds = 6000
}}
foreach ($badJson in @(
    '{{"advisory_released":false}}',
    '{{"advisory_released":true,"extra":1}}',
    '{{"advisory_released":"true"}}'
)) {{
    $script:resultJson = $badJson
    $rejected = $false
    try {{ [void](Invoke-TicketboxPostgresqlWriterFenceReconcile @base) }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "accepted invalid reconcile evidence: $badJson" }}
}}
if ($script:sqlCalls -ne 3) {{ throw 'result-evidence SQL call count drifted' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
