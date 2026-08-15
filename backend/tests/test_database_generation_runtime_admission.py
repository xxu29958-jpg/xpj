"""Installed runtime admission against the sole database-generation CURRENT."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.database._database_generation_runtime_admission as admission

TARGET_REVISION = "20260809_0001"


def _authority_documents() -> tuple[str, dict[str, object], dict[str, object]]:
    operation_id = "11111111-1111-4111-8111-111111111111"
    installation_id = "22222222-2222-4222-8222-222222222222"
    program_sha = "a" * 64
    intent_sha = "b" * 64
    binding = {
        "schema": "ticketbox-database-generation-database-binding-v1",
        "operation_id": operation_id,
        "installation_id": installation_id,
        "intent_sha256": intent_sha,
        "source_binding_sha256": "c" * 64,
        "target_revision": TARGET_REVISION,
        "generation_program_sha256": program_sha,
        "execution_authority_sha256": "d" * 64,
        "role_authority_sha256": "e" * 64,
        "runtime_acl_sha256": "f" * 64,
        "post_migration_writer_fence_sha256": "1" * 64,
        "target_recovery_evidence_sha256": "2" * 64,
    }
    binding_json = admission._canonical_json(binding)
    current = {
        "schema": "ticketbox-current-database-generation-v1",
        "operation_id": operation_id,
        "installation_id": installation_id,
        "intent_sha256": intent_sha,
        "candidate_sha256": "3" * 64,
        "committed_revision": TARGET_REVISION,
        "generation_program_sha256": program_sha,
        "database_binding_sha256": hashlib.sha256(binding_json.encode()).hexdigest(),
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


@dataclass(frozen=True)
class _Connection:
    live: _LiveDatabase

    def scalar(self, *_args: object, **_kwargs: object) -> str:
        return self.live.binding_json

    def scalars(self, *_args: object, **_kwargs: object) -> tuple[str, ...]:
        return self.live.revisions


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
        current["database_binding_sha256"] = hashlib.sha256(
            live.binding_json.encode()
        ).hexdigest()
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

    reject = partial(
        _assert_rejected,
        live=live,
        engine=engine,
        program=program,
        current_path=current_path,
    )
    reject(current_updates={"candidate_sha256": "not-a-digest"})
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
    reject(current_updates={"expected_predecessor_sha256": "4" * 64})
    reject(current_updates={"generation_program_sha256": "4" * 64})
    reject(
        binding_updates={"generation_program_sha256": "4" * 64},
        current_updates={"generation_program_sha256": "4" * 64},
    )
    reject(bind_current_payload_digest=False)
