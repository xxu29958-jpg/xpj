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
C07_LIFECYCLE = PACKAGING / "windows_c07_lifecycle.ps1"
INSTALLATION_SAFETY = PACKAGING / "windows_installation_safety.ps1"
C07_POLICY = PACKAGING / "c07_lifecycle" / "writer_fence.ps1"
C07_POLICY_COMPONENTS = (
    PACKAGING / "c07_lifecycle" / "writer_fence" / "policy.ps1",
    PACKAGING / "c07_lifecycle" / "writer_fence" / "adapter.ps1",
)
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
    (
        r"c07_lifecycle\writer_fence.ps1",
        r"{app}\installer\c07_lifecycle",
        "C07WriterFenceScript",
        r"packaging\c07_lifecycle\writer_fence.ps1",
    ),
    (
        r"c07_lifecycle\writer_fence\policy.ps1",
        r"{app}\installer\c07_lifecycle\writer_fence",
        "C07WriterFencePolicyScript",
        r"packaging\c07_lifecycle\writer_fence\policy.ps1",
    ),
    (
        r"c07_lifecycle\writer_fence\adapter.ps1",
        r"{app}\installer\c07_lifecycle\writer_fence",
        "C07WriterFenceAdapterScript",
        r"packaging\c07_lifecycle\writer_fence\adapter.ps1",
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


def test_writer_fence_has_small_c07_free_components_and_retires_old_mechanics() -> None:
    loader = LOADER.read_text(encoding="utf-8-sig")
    sources = [path.read_text(encoding="utf-8-sig") for path in COMPONENTS]
    generic = loader + "\n" + "\n".join(sources)
    c07_lifecycle = C07_LIFECYCLE.read_text(encoding="utf-8-sig")
    c07_policy = C07_POLICY.read_text(encoding="utf-8-sig") + "\n" + "\n".join(
        path.read_text(encoding="utf-8-sig") for path in C07_POLICY_COMPONENTS
    )

    for path in (LOADER, *COMPONENTS, C07_POLICY, *C07_POLICY_COMPONENTS):
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
        "NOT EXISTS (\n                      SELECT 1\n                      FROM pg_stat_activity AS visible_activity",
        "ALTER ROLE %I NOLOGIN CONNECTION LIMIT 0",
        "REVOKE CONNECT ON DATABASE %I FROM %I",
        "relation.relkind IN ('r', 'p', 'f', 'S', 'v')",
        "relation.relkind = 'v'",
        "has_any_column_privilege(",
        "FROM information_schema.views AS view_capability",
        "view_capability.is_insertable_into = 'YES'",
        "view_capability.is_trigger_insertable_into = 'YES'",
        "view_capability.is_updatable = 'YES'",
        "view_capability.is_trigger_updatable = 'YES'",
        "view_capability.is_trigger_deletable = 'YES'",
        "$NamespaceAlias.nspname <> 'information_schema'",
        "$NamespaceAlias.nspname !~ '^pg_'",
        "has_schema_privilege(role.oid, namespace.oid, 'USAGE')",
    ):
        assert required in generic
    assert generic.count("relation.relkind IN ('r', 'p', 'f', 'S', 'v')") == 3
    assert generic.count("relation.relkind = 'v'") == 2
    assert generic.count(
        "FROM information_schema.views AS view_capability"
    ) == 2
    assert generic.count("has_any_column_privilege(") == 6
    assert generic.count("New-TicketboxPostgresqlWriterFenceUserNamespacePredicateSql") == 5
    assert generic.count(
        "New-TicketboxPostgresqlWriterFenceExecutableRelationScopeSql"
    ) == 3
    assert generic.count("$NamespaceAlias.nspname <> 'information_schema'") == 1
    assert generic.count("$NamespaceAlias.nspname !~ '^pg_'") == 1
    assert "OR (\n            NOT EXISTS (" in generic

    authority_source = (PACKAGING / "windows_c07_heartbeat_authority.ps1").read_text(
        encoding="utf-8-sig"
    )
    adapter_source = C07_POLICY_COMPONENTS[1].read_text(encoding="utf-8-sig")
    comparator_definition = (
        "function Test-TicketboxC07WriterFenceRoleIdentitySetEquals"
    )
    assert authority_source.count(comparator_definition) == 1
    assert comparator_definition not in adapter_source

    for retired in (
        "pg_try_advisory_lock(",
        "pg_advisory_unlock(",
        "pg_terminate_backend(",
        "ALTER ROLE %I NOLOGIN CONNECTION LIMIT 0",
    ):
        assert retired not in c07_lifecycle

    assert "Get-TicketboxPostgresqlWriterFenceObservation" in c07_policy
    assert "Invoke-TicketboxPostgresqlWriterFenceReconcile" in c07_policy
    assert "inert_unregistered" in c07_policy


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
            "Flags: ignoreversion"
        ) in active_inno_lines
        assert re.search(
            rf'Assert-File\s+`\s*\${variable}\s+`\s*"[^"]+"',
            active_build,
        )
        assert f'"{recipe_path}",' in recipe


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_writer_fence_loaders_guard_every_component(engine: str) -> None:
    all_components = (*COMPONENTS, *C07_POLICY_COMPONENTS)
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
. '{_literal(C07_POLICY)}'
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


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_policy_classifies_generic_role_facts_without_leaking_into_adapter(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxC07MigratorRole = 'ticketbox_migrator'
$script:TicketboxC07OwnerRole = 'ticketbox_owner'
$script:TicketboxC07LegacyRuntimeRole = 'ticketbox'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
. '{_literal(C07_POLICY_COMPONENTS[0])}'
function New-RoleFact(
    [string]$Name,
    [int64]$Oid,
    [bool]$CanLogin,
    [bool]$IsSuperuser,
    [bool]$CanWrite
) {{
    return [pscustomobject]@{{
        name = $Name
        oid = $Oid
        can_login = $CanLogin
        connection_limit = -1
        is_superuser = $IsSuperuser
        can_create_db = $false
        can_create_role = $false
        can_replicate = $false
        can_bypass_rls = $false
        is_database_owner = ($Name -ceq 'ticketbox_owner')
        owns_managed_schema = ($Name -ceq 'ticketbox_owner')
        owns_managed_relations = ($Name -ceq 'ticketbox_owner')
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $CanLogin
        effective_connect = $CanLogin
        can_database_create = ($Name -ceq 'ticketbox_owner')
        can_managed_schema_create = ($Name -ceq 'ticketbox_owner')
        can_table_write = $CanWrite
        can_sequence_write = $CanWrite
        can_assume_write_owner = ($Name -ceq 'ticketbox_migrator')
        predefined_role_usage = if ($Name -ceq 'ticketbox_owner') {{
            @('pg_database_owner')
        }} else {{ @() }}
        predefined_role_set = if (
            $Name -ceq 'ticketbox_migrator' -or
            $Name -ceq 'ticketbox_owner'
        ) {{
            @('pg_database_owner')
        }} else {{ @() }}
    }}
}}
$raw = [pscustomobject]@{{
    PublicConnect = $true
    OtherClientSessionCount = 0
    ClientSessions = @()
    MaxPreparedTransactions = 0
    PreparedTransactionCount = 0
    LogicalSubscriptionCount = 0
    LogicalApplyWorkerCount = 0
    UnexpectedDatabaseWorkerCount = 0
    AdvisoryFenceAvailable = $true
    AdvisoryFenceReleased = $true
    Roles = @(
        (New-RoleFact 'postgres' 10 $true $true $true),
        (New-RoleFact 'ticketbox_migrator' 11 $true $false $false),
        (New-RoleFact 'ticketbox_owner' 12 $false $false $true),
        (New-RoleFact 'ticketbox_runtime' 13 $true $false $true),
        (New-RoleFact 'inert_role' 14 $false $false $false)
    )
}}
$classified = ConvertTo-TicketboxC07WriterFenceObservation `
    -RawObservation $raw `
    -AuthorityPhase 'managed_frozen'
if ($classified.Roles[0].disposition -cne 'database_authority') {{
    throw 'database authority classification mismatch'
}}
if ($classified.Roles[3].disposition -cne 'fenced_runtime') {{
    throw 'runtime classification mismatch'
}}
if ($classified.Roles[4].disposition -cne 'inert_unregistered') {{
    throw 'inert classification mismatch'
}}
$raw.Roles[4].can_login = $true
$rejected = $false
try {{
    [void](ConvertTo-TicketboxC07WriterFenceObservation `
        -RawObservation $raw `
        -AuthorityPhase 'managed_frozen')
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'unregistered login role was accepted' }}
$raw.Roles[4].can_login = $false
function Assert-C07PolicyRejected([string]$Label, [scriptblock]$Mutate) {{
    $candidate = $raw | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    & $Mutate $candidate
    $failed = $false
    try {{
        [void](ConvertTo-TicketboxC07WriterFenceObservation `
            -RawObservation $candidate `
            -AuthorityPhase 'managed_frozen')
    }}
    catch {{ $failed = $true }}
    if (-not $failed) {{ throw "accepted C07 writer bypass: $Label" }}
}}
Assert-C07PolicyRejected 'prepared transaction' {{
    param($item) $item.PreparedTransactionCount = 1
}}
Assert-C07PolicyRejected 'busy advisory lease' {{
    param($item) $item.AdvisoryFenceAvailable = $false
}}
Assert-C07PolicyRejected 'unregistered direct connect' {{
    param($item) $item.Roles[4].direct_connect = $true
}}
Assert-C07PolicyRejected 'unregistered table writer' {{
    param($item) $item.Roles[4].can_table_write = $true
}}
Assert-C07PolicyRejected 'unregistered owner membership' {{
    param($item) $item.Roles[4].can_assume_write_owner = $true
}}
Assert-C07PolicyRejected 'runtime predefined writer role' {{
    param($item) $item.Roles[3].predefined_role_usage = @('pg_write_all_data')
}}
Assert-C07PolicyRejected 'migrator predefined server role' {{
    param($item)
    $item.Roles[1].predefined_role_set = @(
        'pg_database_owner',
        'pg_execute_server_program'
    )
}}
Assert-C07PolicyRejected 'migrator inherits owner capability' {{
    param($item)
    $item.Roles[1].predefined_role_usage = @('pg_database_owner')
}}
Assert-C07PolicyRejected 'migrator has direct table write' {{
    param($item) $item.Roles[1].can_table_write = $true
}}
Assert-C07PolicyRejected 'migrator has direct sequence write' {{
    param($item) $item.Roles[1].can_sequence_write = $true
}}
Assert-C07PolicyRejected 'owner extra predefined role' {{
    param($item) $item.Roles[2].predefined_role_usage = @(
        'pg_database_owner',
        'pg_write_all_data'
    )
}}
Assert-C07PolicyRejected 'elevated migrator' {{
    param($item) $item.Roles[1].is_superuser = $true
}}
Assert-C07PolicyRejected 'login owner' {{
    param($item) $item.Roles[2].can_login = $true
}}
Assert-C07PolicyRejected 'elevated runtime' {{
    param($item) $item.Roles[3].can_create_role = $true
}}
Assert-C07PolicyRejected 'runtime owns database' {{
    param($item) $item.Roles[3].is_database_owner = $true
}}
Assert-C07PolicyRejected 'runtime owns schema' {{
    param($item) $item.Roles[3].owns_managed_schema = $true
}}
Assert-C07PolicyRejected 'runtime assumes owner' {{
    param($item) $item.Roles[3].can_assume_write_owner = $true
}}
Assert-C07PolicyRejected 'runtime owns security definer routine' {{
    param($item) $item.Roles[3].owns_security_definer_routines = $true
}}
Assert-C07PolicyRejected 'runtime executes unowned security definer routine' {{
    param($item)
    $item.Roles[3].can_execute_unowned_security_definer_routines = $true
}}
Assert-C07PolicyRejected 'migrator owns security definer routine' {{
    param($item) $item.Roles[1].owns_security_definer_routines = $true
}}
Assert-C07PolicyRejected 'owner lost database ownership' {{
    param($item) $item.Roles[2].is_database_owner = $false
}}
Assert-C07PolicyRejected 'migrator lost owner membership' {{
    param($item) $item.Roles[1].can_assume_write_owner = $false
}}
Assert-C07PolicyRejected 'missing database authority' {{
    param($item)
    $item.Roles = @($item.Roles | Where-Object {{ $_.name -cne 'postgres' }})
}}
Assert-C07PolicyRejected 'missing runtime writer' {{
    param($item)
    $item.Roles = @(
        $item.Roles |
            Where-Object {{ $_.name -cne 'ticketbox_runtime' }}
    )
}}
Assert-C07PolicyRejected 'missing nologin owner' {{
    param($item)
    $item.Roles = @(
        $item.Roles |
            Where-Object {{ $_.name -cne 'ticketbox_owner' }}
    )
}}
Assert-C07PolicyRejected 'missing migrator' {{
    param($item)
    $item.Roles = @(
        $item.Roles |
            Where-Object {{ $_.name -cne 'ticketbox_migrator' }}
    )
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_legacy_only_topology_is_auto_classified_and_bound_to_intent(
    engine: str,
    tmp_path: Path,
) -> None:
    absent_path = tmp_path / f"absent-{Path(engine).stem}.json"
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxC07DatabaseName = 'ticketbox'
$script:TicketboxC07MigratorRole = 'ticketbox_migrator'
$script:TicketboxC07OwnerRole = 'ticketbox_owner'
$script:TicketboxC07LegacyRuntimeRole = 'ticketbox'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
$script:TicketboxC07WriterFenceIntentSchema =
    'ticketbox-c07-writer-fence-intent-v4'
. '{_literal(C07_POLICY_COMPONENTS[0])}'
. '{_literal(C07_POLICY_COMPONENTS[1])}'
function New-LegacyRoleFact(
    [string]$Name,
    [int64]$Oid,
    [bool]$CanLogin,
    [bool]$IsSuperuser,
    [bool]$IsOwner
) {{
    return [pscustomobject]@{{
        name = $Name
        oid = $Oid
        can_login = $CanLogin
        connection_limit = -1
        is_superuser = $IsSuperuser
        can_create_db = $false
        can_create_role = $false
        can_replicate = $false
        can_bypass_rls = $false
        is_database_owner = $IsOwner
        owns_managed_schema = $IsOwner
        owns_managed_relations = $IsOwner
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $CanLogin
        effective_connect = $true
        can_database_create = $IsOwner
        can_managed_schema_create = $IsOwner
        can_table_write = $IsOwner
        can_sequence_write = $IsOwner
        can_assume_write_owner = $false
        predefined_role_usage = if ($IsOwner) {{ @('pg_database_owner') }} else {{ @() }}
        predefined_role_set = if ($IsOwner) {{ @('pg_database_owner') }} else {{ @() }}
    }}
}}
$script:raw = [pscustomobject]@{{
    PublicConnect = $true
    OtherClientSessionCount = 0
    ClientSessions = @()
    MaxPreparedTransactions = 0
    PreparedTransactionCount = 0
    LogicalSubscriptionCount = 0
    LogicalApplyWorkerCount = 0
    UnexpectedDatabaseWorkerCount = 0
    AdvisoryFenceAvailable = $true
    AdvisoryFenceReleased = $true
    Roles = @(
        (New-LegacyRoleFact 'postgres' 10 $true $true $false),
        (New-LegacyRoleFact 'ticketbox' 11 $true $false $true)
    )
}}
function Get-TicketboxC07RawWriterDatabaseFenceObservation {{ return $script:raw }}
$classified = Get-TicketboxC07WriterDatabaseFenceObservation
if (
    [string]$classified.AuthorityPhase -cne 'legacy_owner_frozen' -or
    @($classified.Roles | Where-Object disposition -CEQ 'legacy_owner_writer').Count -ne 1
) {{
    throw 'legacy-only source was not auto-classified from owner facts'
}}

$script:capturedIntent = $null
function Get-TicketboxC07WriterFenceIntentPath {{
    return '{_literal(absent_path)}'
}}
function Write-TicketboxC07HostEnvelope {{
    param($Path, $ArtifactKind, $Payload)
    $script:capturedIntent = [pscustomobject]@{{
        Payload = [pscustomobject]$Payload
        PayloadSha256 = ('F' * 64)
        IntentSchema = [string]$Payload.schema
        IsLegacyV3 = $false
        OperationMode = [string]$Payload.operation_mode
        AuthorityPhase = [string]$Payload.authority_phase
        PublicConnect = [bool]$Payload.public_connect
        Roles = @($Payload.roles)
    }}
}}
function Read-TicketboxC07WriterFenceIntent {{ return $script:capturedIntent }}
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        database_binding_sha256 = ('B' * 64)
    }}
    Descriptor = [pscustomobject]@{{ PayloadSha256 = ('A' * 64) }}
}}
$intent = Initialize-TicketboxC07WriterFenceIntent `
    -Authority $authority `
    -ServiceStartPolicy 'delayed_auto' `
    -Observation $classified `
    -OperationMode 'legacy_adoption' `
    -AuthorityPhase ([string]$classified.AuthorityPhase)
if (
    [string]$intent.Payload.schema -cne
        'ticketbox-c07-writer-fence-intent-v4' -or
    [string]$intent.OperationMode -cne 'legacy_adoption' -or
    [string]$intent.AuthorityPhase -cne 'legacy_owner_frozen'
) {{
    throw 'legacy-only classification was not durably bound into intent'
}}

$script:raw.Roles += New-LegacyRoleFact `
    'ticketbox_owner' 12 $false $false $false
$partialRejected = $false
try {{ [void](Get-TicketboxC07WriterDatabaseFenceObservation) }}
catch {{ $partialRejected = $true }}
if (-not $partialRejected) {{
    throw 'legacy-only source accepted partial target-role residue'
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_adapter_binds_exact_writer_fence_policy_and_reverifies(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxC07DatabaseName = 'ticketbox'
$script:TicketboxC07MigratorRole = 'ticketbox_migrator'
$script:TicketboxC07OwnerRole = 'ticketbox_owner'
$script:TicketboxC07LegacyRuntimeRole = 'ticketbox'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
$script:TicketboxC07ActiveMaintenanceBudget = $null
$script:fenced = $false
$script:observationCalls = @()
$script:reconcileCalls = @()
$script:databaseAuthorityCredential = New-Object Security.SecureString
foreach ($character in 'secret'.ToCharArray()) {{
    $script:databaseAuthorityCredential.AppendChar($character)
}}
$script:databaseAuthorityCredential.MakeReadOnly()
$script:poisonAmbient = $false
function Get-TicketboxC07DatabaseAuthorityCredential {{
    if ($script:poisonAmbient) {{ throw 'ambient credential used' }}
    $script:databaseAuthorityCredential
}}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    if ($script:poisonAmbient) {{ throw 'ambient host authority used' }}
    [pscustomobject]@{{ PsqlPath = 'C:\\pg\\psql.exe' }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
function Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds {{
    param($MaximumMilliseconds, $Label)
    if ($script:poisonAmbient) {{ throw 'ambient deadline used' }}
    return [int]$MaximumMilliseconds
}}
function New-TicketboxC07LocalDatabaseUrl {{
    param($Authority, $Database, $Role)
    if ($Database -cne 'ticketbox' -or $Role -cne 'postgres') {{
        throw 'C07 database authority URL policy drifted'
    }}
    'postgresql://postgres@127.0.0.1:5432/ticketbox'
}}
    function Invoke-TicketboxC07WithPlainSecret {{
        param($Secret, [scriptblock]$Action)
        & $Action 'secret'
    }}
function Test-TicketboxC07WriterFenceRoleIdentitySetEquals {{
    param($Left, $Right)
    if (@($Left).Count -ne @($Right).Count) {{ return $false }}
    for ($index = 0; $index -lt @($Left).Count; $index++) {{
        if (
            [string]$Left[$index].name -cne [string]$Right[$index].name -or
            [int64]$Left[$index].oid -ne [int64]$Right[$index].oid
        ) {{ return $false }}
    }}
    return $true
}}
function New-GenericRole(
    [string]$Name,
    [int64]$Oid,
    [string]$Kind
) {{
    $isAuthority = $Kind -ceq 'authority'
    $isMigrator = $Kind -ceq 'migrator'
    $isOwner = $Kind -ceq 'owner'
    $isRuntime = $Kind -ceq 'runtime'
    $login = $isAuthority -or $isMigrator -or ($isRuntime -and -not $script:fenced)
    return [pscustomobject]@{{
        name = $Name
        oid = $Oid
        can_login = $login
        connection_limit = if ($isRuntime -and $script:fenced) {{ 0 }} else {{ -1 }}
        is_superuser = $isAuthority
        can_create_db = $isAuthority
        can_create_role = $isAuthority
        can_replicate = $isAuthority
        can_bypass_rls = $isAuthority
        is_database_owner = $isOwner
        owns_managed_schema = $isOwner
        owns_managed_relations = $isOwner
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $login
        effective_connect = $login
        can_database_create = $isOwner
        can_managed_schema_create = $isOwner
        can_table_write = $isAuthority -or $isOwner -or $isRuntime
        can_sequence_write = $isAuthority -or $isOwner -or $isRuntime
        can_assume_write_owner = $isMigrator
        predefined_role_usage = if ($isOwner) {{
            @('pg_database_owner')
        }} else {{ @() }}
        predefined_role_set = if ($isMigrator -or $isOwner) {{
            @('pg_database_owner')
        }} else {{ @() }}
    }}
}}
function New-RawObservation {{
    [pscustomobject]@{{
        PublicConnect = -not $script:fenced
        OtherClientSessionCount = 0
        ClientSessions = @()
        MaxPreparedTransactions = 0
        PreparedTransactionCount = 0
        LogicalSubscriptionCount = 0
        LogicalApplyWorkerCount = 0
        UnexpectedDatabaseWorkerCount = 0
        AdvisoryFenceAvailable = $true
        AdvisoryFenceReleased = $true
        Roles = @(
            (New-GenericRole 'postgres' 10 'authority'),
            (New-GenericRole 'ticketbox_migrator' 11 'migrator'),
            (New-GenericRole 'ticketbox_owner' 12 'owner'),
            (New-GenericRole 'ticketbox' 13 'retired'),
            (New-GenericRole 'ticketbox_runtime' 14 'runtime')
        )
    }}
}}
function Get-TicketboxPostgresqlWriterFenceObservation {{
    param(
        $PsqlPath, $DatabaseUrl, $Password, $ManagedSchemaName,
        $AdvisoryLockLabel, $ApplicationName, $TimeoutMilliseconds,
        $StatementTimeoutMilliseconds, $LockTimeoutMilliseconds
    )
    $script:observationCalls += [pscustomobject]@{{
        PsqlPath = $PsqlPath
        DatabaseUrl = $DatabaseUrl
        Password = $Password
        ManagedSchemaName = $ManagedSchemaName
        AdvisoryLockLabel = $AdvisoryLockLabel
        ApplicationName = $ApplicationName
        TimeoutMilliseconds = $TimeoutMilliseconds
        StatementTimeoutMilliseconds = $StatementTimeoutMilliseconds
        LockTimeoutMilliseconds = $LockTimeoutMilliseconds
    }}
    New-RawObservation
}}
function Invoke-TicketboxPostgresqlWriterFenceReconcile {{
    param(
        $PsqlPath, $DatabaseUrl, $Password, $AuthorityRole,
        $ManagedSchemaName, $AdvisoryLockLabel, $ApplicationName,
        $ManagedWriterRoles, $AuthorizedRoleNames, $AllowedLoginRolesAfterFence,
        $AllowedDatabaseOwnerRoles, $AllowedManagedWriterOwnerRoles,
        $AllowedDatabaseOwnerTransitionRoles,
        $TimeoutMilliseconds, $LockTimeoutMilliseconds,
        $TerminationTimeoutMilliseconds
    )
    $script:reconcileCalls += [pscustomobject]@{{
        AuthorityRole = $AuthorityRole
        ManagedSchemaName = $ManagedSchemaName
        AdvisoryLockLabel = $AdvisoryLockLabel
        ApplicationName = $ApplicationName
        ManagedWriterRoles = @($ManagedWriterRoles)
        AuthorizedRoleNames = @($AuthorizedRoleNames)
        AllowedLoginRolesAfterFence = @($AllowedLoginRolesAfterFence)
        AllowedDatabaseOwnerRoles = @($AllowedDatabaseOwnerRoles)
        AllowedManagedWriterOwnerRoles = @($AllowedManagedWriterOwnerRoles)
        AllowedDatabaseOwnerTransitionRoles =
            @($AllowedDatabaseOwnerTransitionRoles)
        TimeoutMilliseconds = $TimeoutMilliseconds
        LockTimeoutMilliseconds = $LockTimeoutMilliseconds
        TerminationTimeoutMilliseconds = $TerminationTimeoutMilliseconds
    }}
    $script:fenced = $true
    [pscustomobject]@{{ AdvisoryFenceReleased = $true }}
}}
. '{_literal(C07_POLICY_COMPONENTS[0])}'
. '{_literal(C07_POLICY_COMPONENTS[1])}'
$before = Get-TicketboxC07WriterDatabaseFenceObservation `
    -AuthorityPhase 'managed_frozen'
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{ operation_id = '01234567-89ab-cdef-0123-456789abcdef' }}
    ReleaseIdentity = [pscustomobject]@{{}}
}}
$intent = [pscustomobject]@{{
    AuthorityPhase = 'managed_frozen'
    PublicConnect = [bool]$before.PublicConnect
    Roles = @($before.Roles)
    Payload = [pscustomobject]@{{
        authority_phase = 'managed_frozen'
        public_connect = [bool]$before.PublicConnect
        roles = @($before.Roles)
    }}
}}
$after = Enter-TicketboxC07WriterDatabaseFence -Authority $authority -Intent $intent
if (
    $script:observationCalls.Count -ne 3 -or
    $script:reconcileCalls.Count -ne 1
) {{
    throw 'C07 adapter did not observe, reconcile, and re-observe exactly once'
}}
foreach ($call in $script:observationCalls) {{
    if (
        $call.PsqlPath -cne 'C:\\pg\\psql.exe' -or
        $call.Password -cne 'secret' -or
        $call.ManagedSchemaName -cne 'public' -or
        $call.AdvisoryLockLabel -cne 'xiaopiaojia:schema' -or
        $call.ApplicationName -cne 'ticketbox-c07-fence-observation' -or
        $call.TimeoutMilliseconds -ne 30000 -or
        $call.StatementTimeoutMilliseconds -ne 5000 -or
        $call.LockTimeoutMilliseconds -ne 1000
    ) {{ throw 'C07 observation policy binding drifted' }}
}}
$call = $script:reconcileCalls[0]
if (
    $call.AuthorityRole -cne 'postgres' -or
    $call.ManagedSchemaName -cne 'public' -or
    $call.AdvisoryLockLabel -cne 'xiaopiaojia:schema' -or
    $call.ApplicationName -cne
        'ticketbox-c07-fence:01234567-89ab-cdef-0123-456789abcdef' -or
    [string]::Join(',', $call.ManagedWriterRoles) -cne
        'ticketbox,ticketbox_runtime' -or
    [string]::Join(',', $call.AllowedLoginRolesAfterFence) -cne
        'postgres,ticketbox_migrator' -or
    [string]::Join(',', $call.AllowedDatabaseOwnerRoles) -cne
        'ticketbox_owner' -or
    @($call.AllowedManagedWriterOwnerRoles).Count -ne 0 -or
    [string]::Join(',', $call.AllowedDatabaseOwnerTransitionRoles) -cne
        'ticketbox_migrator' -or
    $call.TimeoutMilliseconds -ne 3600000 -or
    $call.LockTimeoutMilliseconds -ne 1000 -or
    $call.TerminationTimeoutMilliseconds -ne 3000 -or
    [bool]$after.PublicConnect
) {{ throw 'C07 reconcile policy binding or post-fence proof drifted' }}
$script:poisonAmbient = $true
$explicitAuthority = [pscustomobject]@{{ PsqlPath = 'C:\\pg\\psql.exe' }}
[void](Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority `
    -HostAuthority $explicitAuthority `
    -DatabaseAuthorityCredential $script:databaseAuthorityCredential `
    -TimeoutMilliseconds 7000)
[void](Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority `
    -HostAuthority $explicitAuthority `
    -DatabaseAuthorityCredential $script:databaseAuthorityCredential `
    -TimeoutMilliseconds 1200)
$invalidTimeoutsRejected = 0
foreach ($invalidTimeout in @(999, 30001)) {{
    try {{
        [void](Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority `
            -HostAuthority $explicitAuthority `
            -DatabaseAuthorityCredential $script:databaseAuthorityCredential `
            -TimeoutMilliseconds $invalidTimeout)
    }}
    catch {{ $invalidTimeoutsRejected += 1 }}
}}
if (
    $script:observationCalls.Count -ne 5 -or
    $invalidTimeoutsRejected -ne 2 -or
    $script:observationCalls[3].TimeoutMilliseconds -ne 7000 -or
    $script:observationCalls[3].StatementTimeoutMilliseconds -ne 5000 -or
    $script:observationCalls[3].LockTimeoutMilliseconds -ne 1000 -or
    $script:observationCalls[4].TimeoutMilliseconds -ne 1200 -or
    $script:observationCalls[4].StatementTimeoutMilliseconds -ne 1200 -or
    $script:observationCalls[4].LockTimeoutMilliseconds -ne 1000
) {{ throw 'explicit raw observation boundary drifted' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
