from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adr_contract_schema import AdrSchemaError, parse_adr  # noqa: E402
from adr_contract_test_support import valid_adr  # noqa: E402


def _write(tmp_path: Path, content: str, adr_id: str = "0065") -> Path:
    path = tmp_path / f"{adr_id}-fixture.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_schema_v2_exposes_three_states_and_stable_clauses(tmp_path: Path) -> None:
    parsed = parse_adr(_write(tmp_path, valid_adr()))

    assert parsed.metadata.decision_status == "accepted"
    assert parsed.metadata.implementation_status == "implemented"
    assert parsed.metadata.verification_status == "unverified"
    assert "ADR-0065-DECISION" in parsed.clause_ids
    assert "ADR-0065-C01" in parsed.clause_ids


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ('summary = "Deterministic fixture"\n', "missing front matter fields: summary"),
        ('decision_status = "accepted"', "decision_status must be one of"),
        ('schema_version = 2', "schema_version must be 2"),
    ],
)
def test_front_matter_rejects_missing_or_unknown_values(
    tmp_path: Path, needle: str, message: str
) -> None:
    content = valid_adr()
    replacement = "" if needle.endswith("\n") else needle.replace("accepted", "maybe").replace("2", "3")

    with pytest.raises(AdrSchemaError, match=message):
        parse_adr(_write(tmp_path, content.replace(needle, replacement, 1)))


@pytest.mark.parametrize(
    ("implementation", "verification", "message"),
    [
        ("nonconformant", "verified", "nonconformant implementation cannot be verified"),
        ("implemented", "verified", "rejected/superseded decision cannot be currently verified"),
    ],
)
def test_invalid_state_combinations_fail(
    tmp_path: Path,
    implementation: str,
    verification: str,
    message: str,
) -> None:
    decision = "rejected" if implementation == "implemented" else "accepted"
    content = valid_adr(
        decision_status=decision,
        implementation_status=implementation,
        verification_status=verification,
    )

    with pytest.raises(AdrSchemaError, match=message):
        parse_adr(_write(tmp_path, content))


def test_decision_alternatives_consequences_and_reversibility_are_must(
    tmp_path: Path,
) -> None:
    for suffix in ("DECISION", "ALTERNATIVES", "CONSEQUENCES", "REVERSIBILITY"):
        content = valid_adr().replace(f"ADR-0065-{suffix}", f"ADR-0065-REMOVED-{suffix}")
        with pytest.raises(AdrSchemaError, match=f"ADR-0065-{suffix}"):
            parse_adr(_write(tmp_path, content))


def test_alternatives_require_two_real_options(tmp_path: Path) -> None:
    content = valid_adr().replace(
        "- **A. Keep handwritten tables.** Rejected because they drift.\n",
        "",
    )

    with pytest.raises(AdrSchemaError, match="Alternatives must contain at least two options"):
        parse_adr(_write(tmp_path, content))


def test_duplicate_and_foreign_clause_ids_fail(tmp_path: Path) -> None:
    duplicate = valid_adr().replace(
        "Generate every derived view from the authoritative source.",
        "Generate every derived view from the authoritative source.\n\n"
        "### [ADR-0065-C01] Duplicate\n\nDuplicate meaning.",
    )
    with pytest.raises(AdrSchemaError, match="duplicate clause ids"):
        parse_adr(_write(tmp_path, duplicate))

    foreign = valid_adr().replace("ADR-0065-C01", "ADR-9999-C01")
    with pytest.raises(AdrSchemaError, match="foreign/malformed clause ids"):
        parse_adr(_write(tmp_path, foreign))


@pytest.mark.parametrize(
    "wrapper",
    [
        ("```markdown\n", "```\n"),
        ("<!--\n", "-->\n"),
        ("<!--\n", ""),
    ],
)
def test_hidden_contract_sections_do_not_count(
    tmp_path: Path, wrapper: tuple[str, str]
) -> None:
    content = valid_adr()
    first_clause = content.index("## [ADR-0065-SCOPE]")
    hidden = f"{content[:first_clause]}{wrapper[0]}{content[first_clause]}{wrapper[1]}"

    with pytest.raises(AdrSchemaError, match="missing mandatory clause ids"):
        parse_adr(_write(tmp_path, hidden))


def test_cxx_clause_must_belong_to_decision(tmp_path: Path) -> None:
    content = valid_adr().replace(
        "### [ADR-0065-C01] Stable contract",
        "### Stable contract",
    )
    content = content.replace(
        "## [ADR-0065-REFERENCES] References",
        "## [ADR-0065-REFERENCES] References\n\n"
        "### [ADR-0065-C01] Misplaced contract",
    )

    with pytest.raises(AdrSchemaError, match="Cxx clauses must belong to ADR-0065-DECISION"):
        parse_adr(_write(tmp_path, content))


def test_every_h2_requires_stable_clause_identity(tmp_path: Path) -> None:
    content = valid_adr().replace(
        "## [ADR-0065-EVIDENCE] Evidence",
        "## Untracked normative section\n\nMust bypass stable identity.\n\n"
        "## [ADR-0065-EVIDENCE] Evidence",
    )

    with pytest.raises(AdrSchemaError, match="every H2 requires a stable clause id"):
        parse_adr(_write(tmp_path, content))


def test_schema_version_requires_an_integer(tmp_path: Path) -> None:
    content = valid_adr().replace("schema_version = 2", "schema_version = 2.0", 1)

    with pytest.raises(AdrSchemaError, match="schema_version must be 2 as an integer"):
        parse_adr(_write(tmp_path, content))


@pytest.mark.parametrize("field", ["title", "summary", "current_scope"])
def test_generated_table_metadata_rejects_delimiters(tmp_path: Path, field: str) -> None:
    content = valid_adr().replace(
        f'{field} = "',
        f'{field} = "unsafe | ',
        1,
    )

    with pytest.raises(AdrSchemaError, match="table delimiters or newlines"):
        parse_adr(_write(tmp_path, content))


def test_relation_scope_rejects_table_delimiter(tmp_path: Path) -> None:
    content = valid_adr(
        relations=(("depends-on", "0066", "unsafe | generated column"),),
    )

    with pytest.raises(AdrSchemaError, match="relation scope.*table delimiters"):
        parse_adr(_write(tmp_path, content))


def test_history_fingerprint_freezes_complete_body_including_fences(tmp_path: Path) -> None:
    original = parse_adr(_write(tmp_path, valid_adr()))
    evidence_update = parse_adr(
        _write(
            tmp_path,
            valid_adr().replace(
                "- `python backend/scripts/_audit_adr_contracts.py`",
                "- `python backend/scripts/_audit_adr_contracts.py --future-proof`",
            ),
        )
    )
    calibration_update = parse_adr(
        _write(
            tmp_path,
            valid_adr().replace(
                "## [ADR-0065-EVIDENCE] Evidence",
                "## [ADR-0065-CALIBRATION] Current implementation calibration\n\n"
                "Implementation remains partial.\n\n"
                "## [ADR-0065-EVIDENCE] Evidence",
            ),
        )
    )
    decision_update = parse_adr(
        _write(
            tmp_path,
            valid_adr().replace(
                "Generate every derived view from the authoritative source.",
                "Rewrite the accepted decision in place.",
            ),
        )
    )
    fence_update = parse_adr(
        _write(
            tmp_path,
            valid_adr().replace(
                "contract-fixture/0065/v1",
                "contract-fixture/0065/rebound",
            ),
        )
    )
    metadata_update = parse_adr(
        _write(
            tmp_path,
            valid_adr(implementation_status="partial"),
        )
    )
    scope_update = parse_adr(
        _write(
            tmp_path,
            valid_adr().replace("Test-only contract scope", "Expanded semantic scope"),
        )
    )
    relation_update = parse_adr(
        _write(
            tmp_path,
            valid_adr(relations=(("depends-on", "0066", "semantic dependency"),)),
        )
    )

    assert evidence_update.history_fingerprint != original.history_fingerprint
    assert calibration_update.history_fingerprint != original.history_fingerprint
    assert decision_update.history_fingerprint != original.history_fingerprint
    assert fence_update.history_fingerprint != original.history_fingerprint
    assert metadata_update.history_fingerprint == original.history_fingerprint
    assert scope_update.history_fingerprint != original.history_fingerprint
    assert relation_update.history_fingerprint != original.history_fingerprint
