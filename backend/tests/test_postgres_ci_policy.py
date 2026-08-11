from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.postgres_release_policy import (
    POSTGRES_RELEASE_POLICY,
    PostgresReleasePolicy,
    load_postgres_release_policy,
    postgres_server_version,
)
from scripts.verify_scoped_ci_results import Verification, verify

_ROOT = Path(__file__).resolve().parents[2]


def _valid_results(*, scope: str = "true") -> dict[str, str]:
    sha = "a" * 40
    result = "success" if scope == "true" else "skipped"
    return {
        "SCOPE_RESULT": "success",
        "POSTGRES_SCOPE": scope,
        "EXPECTED_SHA": sha,
        "EXPECTED_SOURCE_SHA": sha,
        "AGGREGATOR_SHA": sha,
        "AGGREGATOR_SOURCE_SHA": sha,
        "SCOPE_SHA": sha,
        "SCOPE_SOURCE_SHA": sha,
        "ORDINARY_RESULT": result,
        "REAL_DB_RESULT": result,
        "RECOVERY_RESULT": result,
        "ORDINARY_SHA": sha if scope == "true" else "",
        "ORDINARY_SOURCE_SHA": sha if scope == "true" else "",
        "REAL_DB_SHA": sha if scope == "true" else "",
        "REAL_DB_SOURCE_SHA": sha if scope == "true" else "",
        "RECOVERY_SHA": sha if scope == "true" else "",
        "RECOVERY_SOURCE_SHA": sha if scope == "true" else "",
    }


def _verify(values: dict[str, str]) -> Verification:
    return verify(
        values,
        label="PostgreSQL",
        scope_key="POSTGRES_SCOPE",
        lanes=("ORDINARY", "REAL_DB", "RECOVERY"),
    )


def test_release_policy_covers_the_pinned_windows_postgres_artifact() -> None:
    toolchain = json.loads(
        (_ROOT / "backend" / "packaging" / "windows-build-toolchain.json").read_text(
            encoding="utf-8"
        )
    )
    raw_version = toolchain["installer_vendor_sources"]["postgresql"]["version"]
    runtime = tuple(int(part) for part in raw_version.split("-", 1)[0].split("."))
    runtime = (*runtime, *([0] * (3 - len(runtime))))

    assert POSTGRES_RELEASE_POLICY.minimum <= runtime
    assert runtime < POSTGRES_RELEASE_POLICY.maximum_exclusive
    assert runtime[0] in POSTGRES_RELEASE_POLICY.supported_majors
    assert POSTGRES_RELEASE_POLICY.current_major == runtime[0]
    assert POSTGRES_RELEASE_POLICY.service_image == (
        toolchain["installer_vendor_sources"]["postgresql"]["ci_service_image"]
    )
    assert postgres_server_version(170010) == (17, 10, 0)
    assert POSTGRES_RELEASE_POLICY.verify_server_version(
        "170010", expected_major=17
    ) == (17, 10, 0)
    with pytest.raises(RuntimeError, match="outside the release policy"):
        POSTGRES_RELEASE_POLICY.verify_server_version("170009", expected_major=17)
    with pytest.raises(RuntimeError, match="outside the release policy"):
        POSTGRES_RELEASE_POLICY.verify_server_version("170010", expected_major=18)
    assert json.loads(POSTGRES_RELEASE_POLICY.matrix_json()) == {
        "include": [
            {
                "postgres-major": str(POSTGRES_RELEASE_POLICY.current_major),
                "postgres-image": POSTGRES_RELEASE_POLICY.service_image,
            }
        ]
    }
    with pytest.raises(ValueError, match="one pinned service image"):
        PostgresReleasePolicy(
            minimum=(17, 10, 0),
            maximum_exclusive=(19, 0, 0),
            supported_majors=(17, 18),
            current_major=18,
            service_image="postgres:18.0@sha256:" + ("a" * 64),
        )


@pytest.mark.parametrize(
    "schema",
    ["ticketbox-windows-release-v1", "ticketbox-windows-release-v2"],
)
def test_postgres_policy_accepts_known_windows_release_schemas(
    tmp_path: Path,
    schema: str,
) -> None:
    release_config = json.loads(
        (_ROOT / "backend" / "packaging" / "windows-release-config.json").read_text(
            encoding="utf-8"
        )
    )
    release_config["schema"] = schema
    candidate = tmp_path / "windows-release-config.json"
    candidate.write_text(json.dumps(release_config), encoding="utf-8")

    assert load_postgres_release_policy(candidate) == POSTGRES_RELEASE_POLICY


def test_postgres_policy_rejects_unknown_windows_release_schema(
    tmp_path: Path,
) -> None:
    release_config = json.loads(
        (_ROOT / "backend" / "packaging" / "windows-release-config.json").read_text(
            encoding="utf-8"
        )
    )
    release_config["schema"] = "ticketbox-windows-release-v3"
    candidate = tmp_path / "windows-release-config.json"
    candidate.write_text(json.dumps(release_config), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported Windows release config schema"):
        load_postgres_release_policy(candidate)


@pytest.mark.parametrize("scope", ["true", "false"])
def test_postgres_result_verifier_rejects_every_single_field_mutation(scope: str) -> None:
    baseline = _valid_results(scope=scope)
    assert _verify(baseline).ok
    scope_only = {
        key: value
        for key, value in baseline.items()
        if not key.startswith(("ORDINARY_", "REAL_DB_", "RECOVERY_"))
    }
    assert verify(
        scope_only,
        label="Scope only",
        scope_key="POSTGRES_SCOPE",
        lanes=(),
    ).ok
    mutations = {
        "SCOPE_RESULT": "failure",
        "POSTGRES_SCOPE": "unknown",
        "EXPECTED_SHA": "b" * 40,
        "EXPECTED_SOURCE_SHA": "b" * 40,
        "AGGREGATOR_SHA": "b" * 40,
        "AGGREGATOR_SOURCE_SHA": "b" * 40,
        "SCOPE_SHA": "b" * 40,
        "SCOPE_SOURCE_SHA": "b" * 40,
        "ORDINARY_RESULT": "failure" if scope == "true" else "success",
        "REAL_DB_RESULT": "cancelled" if scope == "true" else "success",
        "RECOVERY_RESULT": "skipped" if scope == "true" else "success",
        "ORDINARY_SHA": "b" * 40,
        "ORDINARY_SOURCE_SHA": "b" * 40,
        "REAL_DB_SHA": "b" * 40,
        "REAL_DB_SOURCE_SHA": "b" * 40,
        "RECOVERY_SHA": "b" * 40,
        "RECOVERY_SOURCE_SHA": "b" * 40,
    }
    for field, value in mutations.items():
        candidate = {**baseline, field: value}
        assert not _verify(candidate).ok, field
    for field in baseline:
        candidate = dict(baseline)
        del candidate[field]
        assert not _verify(candidate).ok, field
