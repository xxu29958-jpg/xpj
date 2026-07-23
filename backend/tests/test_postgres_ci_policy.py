from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.postgres_release_policy import (
    POSTGRES_RELEASE_POLICY,
    PostgresReleasePolicy,
    postgres_server_version,
)
from scripts.verify_postgres_ci_results import verify

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
    multi_major_policy = PostgresReleasePolicy(
        minimum=(17, 10, 0),
        maximum_exclusive=(19, 0, 0),
        supported_majors=(17, 18),
        current_major=18,
        service_image="postgres:18.0@sha256:" + ("a" * 64),
    )
    assert json.loads(multi_major_policy.matrix_json()) == {
        "include": [
            {
                "postgres-major": "18",
                "postgres-image": "postgres:18.0@sha256:" + ("a" * 64),
            }
        ]
    }
    with pytest.raises(RuntimeError, match="matrix coordinate"):
        multi_major_policy.verify_server_version("180000", expected_major=17)


@pytest.mark.parametrize("scope", ["true", "false"])
def test_postgres_result_verifier_rejects_every_single_field_mutation(scope: str) -> None:
    baseline = _valid_results(scope=scope)
    assert verify(baseline).ok
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
        assert not verify(candidate).ok, field
    for field in baseline:
        candidate = dict(baseline)
        del candidate[field]
        assert not verify(candidate).ok, field
