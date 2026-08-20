"""Installed runtime admission against the sole database-generation CURRENT."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.database._database_generation_runtime_admission as admission
import app.database._database_generation_runtime_queries as runtime_queries

TARGET_REVISION = "20260809_0001"
OPERATION_ID = "11111111-1111-4111-8111-111111111111"
INSTALLATION_ID = "22222222-2222-4222-8222-222222222222"
INTENT_SHA256 = "b" * 64
CANDIDATE_SHA256 = "3" * 64
CLUSTER_SYSTEM_IDENTIFIER = "7643222813893222841"
DATABASE_OID = 16384
DATABASE_NAME = "ticketbox"
RUNTIME_ROLE = "ticketbox_runtime"
LOGICAL_SERVER_ID = "55555555-5555-4555-8555-555555555555"
LOGICAL_DATA_GENERATION = "66666666-6666-4666-8666-666666666666"
RUNTIME_ACL_EVIDENCE = (
    "database\tticketbox\tPUBLIC\tCONNECT\tfalse",
    "relation\tpublic.app_meta\tticketbox_runtime\tSELECT\tfalse",
)
RUNTIME_ACL_SHA256 = hashlib.sha256("\n".join(RUNTIME_ACL_EVIDENCE).encode()).hexdigest()
BOOTSTRAP_RETIREMENT = admission._canonical_json(
    {
        "schema": "ticketbox-database-generation-bootstrap-retirement-v1",
        "operation_id": OPERATION_ID,
        "intent_sha256": INTENT_SHA256,
        "candidate_sha256": CANDIDATE_SHA256,
        "committed_revision": TARGET_REVISION,
    }
)


def _authority_documents() -> tuple[str, dict[str, object], dict[str, object]]:
    program_sha = "a" * 64
    binding = {
        "schema": "ticketbox-database-generation-database-binding-v1",
        "operation_id": OPERATION_ID,
        "installation_id": INSTALLATION_ID,
        "intent_sha256": INTENT_SHA256,
        "source_binding_sha256": "c" * 64,
        "target_revision": TARGET_REVISION,
        "generation_program_sha256": program_sha,
        "cluster_system_identifier": CLUSTER_SYSTEM_IDENTIFIER,
        "database_oid": DATABASE_OID,
        "database_name": DATABASE_NAME,
        "runtime_role": RUNTIME_ROLE,
        "logical_server_id": LOGICAL_SERVER_ID,
        "logical_data_generation": LOGICAL_DATA_GENERATION,
        "execution_authority_sha256": "d" * 64,
        "role_authority_sha256": "e" * 64,
        "runtime_acl_sha256": RUNTIME_ACL_SHA256,
        "post_migration_writer_fence_sha256": "1" * 64,
        "target_recovery_evidence_sha256": "2" * 64,
    }
    binding_json = admission._canonical_json(binding)
    current = {
        "schema": "ticketbox-current-database-generation-v1",
        "operation_id": OPERATION_ID,
        "installation_id": INSTALLATION_ID,
        "intent_sha256": INTENT_SHA256,
        "candidate_sha256": CANDIDATE_SHA256,
        "committed_revision": TARGET_REVISION,
        "generation_program_sha256": program_sha,
        "database_binding_sha256": hashlib.sha256(binding_json.encode()).hexdigest(),
        "terminal_state_sha256": "6" * 64,
        "expected_predecessor_sha256": "",
    }
    current_json = admission._canonical_json(current)
    envelope = {
        "schema": "ticketbox-database-generation-envelope-v1",
        "kind": "current",
        "payload_sha256": hashlib.sha256(current_json.encode()).hexdigest(),
        "payload": current,
    }
    return binding_json, current, envelope


@dataclass
class _LiveDatabase:
    binding_json: str = ""
    revisions: tuple[str, ...] = (TARGET_REVISION,)
    cluster_system_identifier: str = CLUSTER_SYSTEM_IDENTIFIER
    database_oid: int = DATABASE_OID
    database_name: str = DATABASE_NAME
    session_user: str = RUNTIME_ROLE
    logical_server_id: str = LOGICAL_SERVER_ID
    logical_data_generation: str = LOGICAL_DATA_GENERATION
    bootstrap_retirement: str = BOOTSTRAP_RETIREMENT
    runtime_capabilities: tuple[bool, ...] = (True,) * 13
    runtime_acl_evidence: tuple[str, ...] = RUNTIME_ACL_EVIDENCE


@dataclass(frozen=True)
class _OneRow:
    row: tuple[object, ...]

    def one(self) -> tuple[object, ...]:
        return self.row


@dataclass(frozen=True)
class _Connection:
    live: _LiveDatabase

    def scalar(self, *_args: object, **_kwargs: object) -> str:
        return self.live.binding_json

    def scalars(self, statement: object, **_kwargs: object) -> tuple[str, ...]:
        sql = str(statement)
        if "public.alembic_version" in sql:
            return self.live.revisions
        if sql == str(runtime_queries.RUNTIME_ACL_EVIDENCE_QUERY):
            return self.live.runtime_acl_evidence
        raise AssertionError(f"unexpected scalar query: {sql}")

    def execute(self, statement: object, **_kwargs: object) -> _OneRow:
        sql = str(statement)
        assert sql == str(runtime_queries.LIVE_DATABASE_QUERY)
        for required_token in (
            "current_database()::text",
            "session_user::text",
            "role.rolsuper",
            "role.rolcreatedb",
            "role.rolconnlimit = -1",
            "role.rolconfig",
            "ticketbox_migrator",
            "ticketbox_owner",
            "pg_auth_members",
            "pg_stat_activity",
            "pg_get_userbyid(database.datdba)",
            "has_database_privilege",
            "has_schema_privilege",
            "pg_class",
            "pg_proc",
            "pg_type",
            "shobj_description",
        ):
            assert required_token in sql
        return _OneRow(
            (
                self.live.cluster_system_identifier,
                self.live.database_oid,
                self.live.database_name,
                self.live.session_user,
                self.live.logical_server_id,
                self.live.logical_data_generation,
                self.live.bootstrap_retirement,
                *self.live.runtime_capabilities,
            )
        )


@dataclass(frozen=True)
class _Engine:
    live: _LiveDatabase

    @contextlib.contextmanager
    def connect(self) -> Iterator[_Connection]:
        yield _Connection(self.live)


@contextlib.contextmanager
def _hold(path: Path) -> Iterator[Path]:
    yield path


def _write_current(
    current_path: Path,
    current: dict[str, object],
    envelope: dict[str, object],
) -> None:
    current_json = admission._canonical_json(current)
    envelope["payload"] = current
    envelope["payload_sha256"] = hashlib.sha256(current_json.encode()).hexdigest()
    current_path.write_text(admission._canonical_json(envelope), encoding="utf-8")


def _assert_rejected(
    *,
    live: _LiveDatabase,
    engine: _Engine,
    program: SimpleNamespace,
    current_path: Path,
    binding_updates: dict[str, object] | None = None,
    current_updates: dict[str, object] | None = None,
    revisions: tuple[str, ...] = (TARGET_REVISION,),
    bind_live_digest: bool = True,
    bind_current_payload_digest: bool = True,
) -> None:
    binding_json, current, envelope = _authority_documents()
    binding = json.loads(binding_json)
    assert isinstance(binding, dict)
    binding.update(binding_updates or {})
    live.binding_json = admission._canonical_json(binding)
    if bind_live_digest:
        current["database_binding_sha256"] = hashlib.sha256(live.binding_json.encode()).hexdigest()
    current.update(current_updates or {})
    live.revisions = revisions
    _write_current(current_path, current, envelope)
    if not bind_current_payload_digest:
        envelope["payload_sha256"] = "0" * 64
        current_path.write_text(admission._canonical_json(envelope), encoding="utf-8")
    with pytest.raises(admission.DatabaseGenerationAdmissionError):
        admission.assert_database_generation_runtime_admission(
            engine,
            program,
            current_path=current_path,
        )


def _assert_live_identity_mutations_rejected(reject: Callable[..., None], live: _LiveDatabase) -> None:
    for binding_field, live_field, hostile in (
        (
            "cluster_system_identifier",
            "cluster_system_identifier",
            "7643222813893222842",
        ),
        ("database_oid", "database_oid", DATABASE_OID + 1),
        ("database_name", "database_name", "ticketbox_clone"),
        ("runtime_role", "session_user", "ticketbox_owner"),
        (
            "logical_server_id",
            "logical_server_id",
            "77777777-7777-4777-8777-777777777777",
        ),
        (
            "logical_data_generation",
            "logical_data_generation",
            "88888888-8888-4888-8888-888888888888",
        ),
    ):
        reject(binding_updates={binding_field: hostile})
        original = getattr(live, live_field)
        setattr(live, live_field, hostile)
        try:
            reject()
        finally:
            setattr(live, live_field, original)


def _assert_closed_runtime_target_mutations_rejected(reject: Callable[..., None], live: _LiveDatabase) -> None:
    for binding_field, live_field, hostile in (
        ("database_name", "database_name", "ticketbox_clone"),
        ("runtime_role", "session_user", "ticketbox_owner"),
    ):
        original = getattr(live, live_field)
        setattr(live, live_field, hostile)
        try:
            reject(binding_updates={binding_field: hostile})
        finally:
            setattr(live, live_field, original)


def _assert_runtime_authority_mutations_rejected(reject: Callable[..., None], live: _LiveDatabase) -> None:
    original_retirement = live.bootstrap_retirement
    live.bootstrap_retirement = ""
    try:
        reject()
    finally:
        live.bootstrap_retirement = original_retirement
    for index in range(len(live.runtime_capabilities)):
        capabilities = list(live.runtime_capabilities)
        capabilities[index] = False
        live.runtime_capabilities = tuple(capabilities)
        try:
            reject()
        finally:
            live.runtime_capabilities = (True,) * 13
    original_acl = live.runtime_acl_evidence
    live.runtime_acl_evidence = (
        *original_acl,
        "relation\tpublic.ledger_audit_logs\tticketbox_runtime\tTRUNCATE\tfalse",
    )
    try:
        reject()
    finally:
        live.runtime_acl_evidence = original_acl


def test_installed_runtime_admission_binds_current_program_and_live_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_path = tmp_path / "current-generation.json"
    live = _LiveDatabase()
    engine = _Engine(live)
    program = SimpleNamespace(
        target_revision=TARGET_REVISION,
        payload_sha256="a" * 64,
    )
    monkeypatch.setattr(admission, "hold_system_runtime_projection_for_read", _hold)

    binding_json, current, envelope = _authority_documents()
    live.binding_json = binding_json
    _write_current(current_path, current, envelope)
    admission.assert_database_generation_runtime_admission(
        engine,
        program,
        current_path=current_path,
    )
    monkeypatch.setattr(
        admission,
        "database_generation_runtime_current_path",
        lambda: current_path,
    )
    admission.assert_database_generation_startup_ready(engine, program)

    reject = partial(
        _assert_rejected,
        live=live,
        engine=engine,
        program=program,
        current_path=current_path,
    )
    reject(current_updates={"candidate_sha256": "not-a-digest"})
    reject(current_updates={"candidate_sha256": "4" * 64})
    reject(
        binding_updates={"operation_id": "33333333-3333-4333-8333-333333333333"},
        bind_live_digest=False,
    )
    for binding_updates in (
        {"operation_id": "33333333-3333-4333-8333-333333333333"},
        {"installation_id": "44444444-4444-4444-8444-444444444444"},
        {"intent_sha256": "4" * 64},
        {"target_revision": "20260808_0001"},
        {"generation_program_sha256": "4" * 64},
    ):
        reject(binding_updates=binding_updates)
    for revisions in ((), ("20260808_0001",), (TARGET_REVISION, "20260808_0001")):
        reject(revisions=revisions)
    _assert_live_identity_mutations_rejected(reject, live)
    _assert_closed_runtime_target_mutations_rejected(reject, live)
    _assert_runtime_authority_mutations_rejected(reject, live)
    reject(current_updates={"expected_predecessor_sha256": "4" * 64})
    reject(current_updates={"generation_program_sha256": "4" * 64})
    reject(
        binding_updates={"generation_program_sha256": "4" * 64},
        current_updates={"generation_program_sha256": "4" * 64},
    )
    reject(bind_current_payload_digest=False)
