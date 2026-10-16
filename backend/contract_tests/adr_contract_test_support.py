"""Small fixture builders for executable ADR contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def valid_adr(
    adr_id: str = "0065",
    *,
    decision_status: str = "accepted",
    implementation_status: str = "implemented",
    verification_status: str = "unverified",
    relations: tuple[tuple[str, str, str], ...] = (),
) -> str:
    relation_toml = "".join(
        f'\n[[relations]]\nkind = "{kind}"\ntarget = "{target}"\nscope = "{scope}"\n'
        for kind, target, scope in relations
    )
    return f'''+++
schema_version = 2
id = "{adr_id}"
title = "Contract fixture {adr_id}"
summary = "Deterministic fixture"
current_scope = "Test-only contract scope"
date = "2026-07-11"
decision_status = "{decision_status}"
implementation_status = "{implementation_status}"
verification_status = "{verification_status}"
decision_type = "governance-calibration"
risk_level = "standard"
confidence = "high"
decision_owner = "decision owner"
implementation_owner = "implementation owner"
verification_owner = "verification owner"
risk_owner = "risk owner"
{relation_toml}+++
# {adr_id} Contract fixture

## [ADR-{adr_id}-SCOPE] Scope

The fixture covers one bounded contract.

## [ADR-{adr_id}-ASSUMPTIONS] Assumptions

The local filesystem is writable.

## [ADR-{adr_id}-DRIVERS] Drivers

The registry must be deterministic.

## [ADR-{adr_id}-ALTERNATIVES] Alternatives

- **A. Keep handwritten tables.** Rejected because they drift.
- **B. Generate views.** Selected because one source can reproduce every view.

## [ADR-{adr_id}-DECISION] Decision

### [ADR-{adr_id}-C01] Stable contract

Generate every derived view from the authoritative source.

```text
contract-fixture/{adr_id}/v1
```

## [ADR-{adr_id}-CONSEQUENCES] Consequences

Generated files must be refreshed whenever metadata changes.

## [ADR-{adr_id}-REVERSIBILITY] Reversibility

The format can be migrated by a versioned converter.

## [ADR-{adr_id}-EVIDENCE] Evidence

- `python backend/scripts/_audit_adr_contracts.py`

## [ADR-{adr_id}-REFERENCES] References

- ADR contract standard.
'''


def write_v2(root: Path, adr_id: str, **kwargs: object) -> Path:
    decisions = root / "docs" / "DECISIONS"
    decisions.mkdir(parents=True, exist_ok=True)
    path = decisions / f"{adr_id}-fixture.md"
    path.write_text(valid_adr(adr_id, **kwargs), encoding="utf-8")
    return path


def baseline_payload(
    entries: list[dict[str, object]] | None = None,
    *,
    bootstrap_base_commit: str = "1" * 40,
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "bootstrap_base_commit": bootstrap_base_commit,
        "entries": [] if entries is None else [{key: row[key] for key in ("id", "path", "sha256")} for row in entries],
    }


def calibration_payload(
    entries: list[dict[str, object]] | None = None,
    *,
    code_baseline: str = "1" * 40,
    portfolio_reviewed_at: str = "2026-07-11",
) -> dict[str, object]:
    fields = (
        "id",
        "path",
        "title",
        "summary",
        "current_scope",
        "decision_status",
        "implementation_status",
        "verification_status",
        "decision_type",
        "risk_level",
        "confidence",
        "owners",
        "relations",
        "reviewed_at",
        "reviewed_against_commit",
        "reason",
    )
    return {
        "schema_version": 2,
        "front_matter_schema_version": 2,
        "portfolio_reviewed_at": portfolio_reviewed_at,
        "code_baseline": code_baseline,
        "baseline_scope": "test fixture",
        "entries": [] if entries is None else [{key: row[key] for key in fields} for row in entries],
    }


def write_baseline(
    root: Path,
    entries: list[dict[str, object]] | None = None,
    *,
    bootstrap_base_commit: str = "1" * 40,
    code_baseline: str = "1" * 40,
) -> Path:
    path = root / "docs" / "DECISIONS" / "legacy-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            baseline_payload(entries, bootstrap_base_commit=bootstrap_base_commit),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    calibration_path = path.with_name("legacy-calibration.json")
    calibration_path.write_text(
        json.dumps(
            calibration_payload(entries, code_baseline=code_baseline),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def legacy_entry(path: Path, adr_id: str) -> dict[str, object]:
    return {
        "id": adr_id,
        "path": f"docs/DECISIONS/{path.name}",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "title": f"Legacy {adr_id}",
        "summary": "Frozen legacy fixture",
        "current_scope": "Legacy scope",
        "decision_status": "accepted",
        "implementation_status": "implemented",
        "verification_status": "unverified",
        "decision_type": "domain",
        "risk_level": "standard",
        "confidence": "medium",
        "owners": {
            "decision": "decision owner",
            "implementation": "implementation owner",
            "verification": "verification owner",
            "risk": "risk owner",
        },
        "relations": [],
        "reviewed_at": "2026-07-11",
        "reviewed_against_commit": "1" * 40,
        "reason": "Initial code-backed calibration",
    }
