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
        source_lanes=(),
    )


@pytest.mark.parametrize("parent,apk", [("true", "true"), ("true", "false"), ("false", "false")])
def test_per_lane_scope_preserves_status_and_both_sha_obligations(parent, apk) -> None:
    values = _valid_results(scope=parent)
    values["APK_SCOPE"] = apk
    for key, value in _valid_results(scope=apk).items():
        if key.startswith("RECOVERY_"):
            values[key] = value
    kwargs = {"label": "Scoped capabilities", "scope_key": "POSTGRES_SCOPE",
              "lanes": ("ORDINARY", "REAL_DB", "RECOVERY"), "source_lanes": (),
              "lane_scopes": {"RECOVERY": "APK_SCOPE"}}
    assert verify(values, **kwargs).ok
    for key in values:
        candidate = dict(values)
        del candidate[key]
        assert not verify(candidate, **kwargs).ok, key
    for lane in kwargs["lanes"]:
        for status in ("failure", "cancelled", "skipped", "success"):
            if status != values[f"{lane}_RESULT"]:
                assert not verify({**values, f"{lane}_RESULT": status}, **kwargs).ok
        for suffix in ("SHA", "SOURCE_SHA"):
            assert not verify({**values, f"{lane}_{suffix}": "wrong-head"}, **kwargs).ok
    for key in ("POSTGRES_SCOPE", "APK_SCOPE"):
        assert not verify({**values, key: "unknown"}, **kwargs).ok


def test_per_lane_scope_cannot_enable_a_child_of_an_unselected_parent() -> None:
    values = {**_valid_results(scope="false"), "APK_SCOPE": "true"}
    assert not verify(values, label="Android", scope_key="POSTGRES_SCOPE",
                      lanes=("ORDINARY", "REAL_DB", "RECOVERY"), source_lanes=(),
                      lane_scopes={"RECOVERY": "APK_SCOPE"}).ok


def test_per_lane_scope_rejects_unknown_lane_and_malformed_cli(monkeypatch) -> None:
    from scripts import verify_scoped_ci_results as scoped

    assert not scoped.verify(_valid_results(), label="Android", scope_key="POSTGRES_SCOPE",
                             lanes=("ORDINARY",), source_lanes=(),
                             lane_scopes={"TYPO": "APK_SCOPE"}).ok
    base = ["--label", "Android", "--scope-key", "ANDROID_SCOPE", "--lane", "APK"]
    for bindings in (["APK"], ["TYPO=APK_SCOPE"], ["APK=bad"], ["APK=APK_SCOPE", "APK=APK_SCOPE"]):
        argv = base + [arg for binding in bindings for arg in ("--lane-scope", binding)]
        with pytest.raises(SystemExit) as error:
            scoped.main(argv)
        assert error.value.code == 2


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
    assert postgres_server_version(170011) == (17, 11, 0)
    assert POSTGRES_RELEASE_POLICY.verify_server_version(
        "170011", expected_major=17
    ) == (17, 11, 0)
    with pytest.raises(RuntimeError, match="outside the release policy"):
        POSTGRES_RELEASE_POLICY.verify_server_version("170010", expected_major=17)
    with pytest.raises(RuntimeError, match="outside the release policy"):
        POSTGRES_RELEASE_POLICY.verify_server_version("170011", expected_major=18)
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
        source_lanes=(),
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


@pytest.mark.parametrize("lane", ("VNEXT", "BUILD"))
def test_scoped_verifier_binds_artifact_lane_to_exact_source_head(lane: str) -> None:
    merge_sha = "a" * 40
    source_sha = "b" * 40
    values = {
        "SCOPE_RESULT": "success",
        "WINDOWS_SCOPE": "true",
        "EXPECTED_SHA": merge_sha,
        "EXPECTED_SOURCE_SHA": source_sha,
        "AGGREGATOR_SHA": merge_sha,
        "AGGREGATOR_SOURCE_SHA": source_sha,
        "SCOPE_SHA": merge_sha,
        "SCOPE_SOURCE_SHA": source_sha,
        "VNEXT_RESULT": "success",
        "VNEXT_SHA": source_sha,
        "VNEXT_SOURCE_SHA": source_sha,
        "BUILD_RESULT": "success",
        "BUILD_SHA": source_sha,
        "BUILD_SOURCE_SHA": source_sha,
    }

    assert verify(
        values,
        label="Windows",
        scope_key="WINDOWS_SCOPE",
        lanes=("VNEXT", "BUILD"),
        source_lanes=("VNEXT", "BUILD"),
    ).ok
    assert not verify(
        {**values, f"{lane}_SHA": merge_sha},
        label="Windows",
        scope_key="WINDOWS_SCOPE",
        lanes=("VNEXT", "BUILD"),
        source_lanes=("VNEXT", "BUILD"),
    ).ok
