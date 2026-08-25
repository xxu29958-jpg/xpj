from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.verify_backend_ci_results import verify

_ROOT = Path(__file__).resolve().parents[2]


def _jobs() -> dict[str, object]:
    workflow = yaml.safe_load((_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]


def _steps(job: dict[str, object]) -> dict[str, dict[str, object]]:
    return {step["name"]: step for step in job["steps"]}


def _valid_results(*, frozen_scope: str, windows_scope: str) -> dict[str, str]:
    # The nested Windows aggregator is stable and returns success for both
    # scoped execution and a verified all-child-jobs-skipped result.
    assert windows_scope in {"true", "false"}
    sha = "a" * 40
    return {
        "SCOPE_RESULT": "success",
        "BACKEND_FROZEN_SCOPE": frozen_scope,
        "BACKEND_CONTRACTS_RESULT": "success",
        "BACKEND_FROZEN_RESULT": "success" if frozen_scope == "true" else "skipped",
        "WINDOWS_PACKAGING_RESULT": "success",
        "EXPECTED_SHA": sha,
        "EXPECTED_SOURCE_SHA": sha,
        "AGGREGATOR_SHA": sha,
        "AGGREGATOR_SOURCE_SHA": sha,
        "SCOPE_SHA": sha,
        "SCOPE_SOURCE_SHA": sha,
        "BACKEND_CONTRACTS_SHA": sha,
        "BACKEND_CONTRACTS_SOURCE_SHA": sha,
        "BACKEND_FROZEN_SHA": sha if frozen_scope == "true" else "",
        "BACKEND_FROZEN_SOURCE_SHA": sha if frozen_scope == "true" else "",
        "WINDOWS_PACKAGING_SHA": sha,
        "WINDOWS_PACKAGING_SOURCE_SHA": sha,
    }


def _assert_windows_build_lane(jobs: dict[str, object]) -> None:
    windows_aggregator = jobs["windows_packaging"]
    assert windows_aggregator["if"] == "${{ always() }}"
    assert _steps(windows_aggregator)["Enforce Windows release lane results"]["run"] == (
        "python -E -S backend/scripts/verify_scoped_ci_results.py "
        '--label "Windows release packaging" --scope-key WINDOWS_SCOPE '
        "--lane VNEXT --lane BUILD"
    )
    windows_steps = _steps(jobs["windows_packaging_build"])
    windows_safety = windows_steps["Windows installer safety behavior"]["run"]
    assert '-m "not xdist_group"' in windows_safety
    assert "-n 4 --dist loadfile --max-worker-restart 0" in windows_safety
    resource_serial = windows_steps["Windows installer resource-serial behavior"]["run"]
    assert "packaging/tests -m xdist_group" in resource_serial
    assert "-n 0 --dist loadfile --max-worker-restart 0" in resource_serial
    assert "Windows local PostgreSQL lifecycle" not in windows_steps
    assert "Database generation projection real PostgreSQL contract" not in windows_steps
    step_names = list(windows_steps)
    prepared = step_names.index("Prepare pinned PostgreSQL and Shawl inputs")
    assert prepared < step_names.index("Windows installer safety behavior")
    assert prepared < step_names.index("Windows installer resource-serial behavior")
    assert prepared < step_names.index("Compile authoritative Inno installer")
    source = (_ROOT / "backend" / "packaging" / "tests" / "test_local_test_postgres_lifecycle.py").read_text(
        encoding="utf-8-sig"
    )
    assert 'pytestmark = pytest.mark.xdist_group(name="windows_postgresql_runtime")' in source


def _assert_backend_required_gate_binds_scope_results_and_exact_checkout_sha() -> None:
    jobs = _jobs()
    backend = jobs["backend"]
    assert backend["needs"] == [
        "scope",
        "backend_contracts",
        "backend_frozen",
        "windows_packaging",
    ]
    assert backend["if"] == "${{ always() }}"
    assert "continue-on-error" not in backend

    for dependency in ("backend_contracts", "backend_frozen", "windows_packaging"):
        job = jobs[dependency]
        assert job["outputs"]["qualification_sha"] == "${{ steps.qualification.outputs.sha }}"
        assert job["outputs"]["qualification_source_sha"] == ("${{ steps.qualification.outputs.source_sha }}")
        assert _steps(job)["Verify qualification SHA"]["id"] == "qualification"

    _assert_windows_build_lane(jobs)

    steps = _steps(backend)
    assert steps["Verify qualification SHA"]["id"] == "qualification"
    enforcement = steps["Enforce required CI results"]
    assert enforcement["run"] == "python -E -S backend/scripts/verify_backend_ci_results.py"
    assert enforcement["env"] == {
        "BASH_ENV": "",
        "ENV": "",
        "SCOPE_RESULT": "${{ needs.scope.result }}",
        "BACKEND_FROZEN_SCOPE": "${{ needs.scope.outputs.backend_frozen }}",
        "BACKEND_CONTRACTS_RESULT": "${{ needs.backend_contracts.result }}",
        "BACKEND_FROZEN_RESULT": "${{ needs.backend_frozen.result }}",
        "WINDOWS_PACKAGING_RESULT": "${{ needs.windows_packaging.result }}",
        "EXPECTED_SHA": "${{ github.sha }}",
        "EXPECTED_SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
        "AGGREGATOR_SHA": "${{ steps.qualification.outputs.sha }}",
        "AGGREGATOR_SOURCE_SHA": "${{ steps.qualification.outputs.source_sha }}",
        "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
        "SCOPE_SOURCE_SHA": "${{ needs.scope.outputs.qualification_source_sha }}",
        "BACKEND_CONTRACTS_SHA": "${{ needs.backend_contracts.outputs.qualification_sha }}",
        "BACKEND_CONTRACTS_SOURCE_SHA": "${{ needs.backend_contracts.outputs.qualification_source_sha }}",
        "BACKEND_FROZEN_SHA": "${{ needs.backend_frozen.outputs.qualification_sha }}",
        "BACKEND_FROZEN_SOURCE_SHA": "${{ needs.backend_frozen.outputs.qualification_source_sha }}",
        "WINDOWS_PACKAGING_SHA": "${{ needs.windows_packaging.outputs.qualification_sha }}",
        "WINDOWS_PACKAGING_SOURCE_SHA": "${{ needs.windows_packaging.outputs.qualification_source_sha }}",
    }


@pytest.mark.parametrize("frozen_scope", ["true", "false"])
@pytest.mark.parametrize("windows_scope", ["true", "false"])
def test_backend_result_verifier_rejects_every_single_field_mutation(
    frozen_scope: str,
    windows_scope: str,
) -> None:
    _assert_backend_required_gate_binds_scope_results_and_exact_checkout_sha()
    baseline = _valid_results(
        frozen_scope=frozen_scope,
        windows_scope=windows_scope,
    )
    assert verify(baseline).ok
    mutations = {
        "SCOPE_RESULT": "failure",
        "BACKEND_FROZEN_SCOPE": "unknown",
        "BACKEND_CONTRACTS_RESULT": "failure",
        "BACKEND_FROZEN_RESULT": ("skipped" if frozen_scope == "true" else "success"),
        "WINDOWS_PACKAGING_RESULT": "skipped",
        "EXPECTED_SHA": "b" * 40,
        "EXPECTED_SOURCE_SHA": "b" * 40,
        "AGGREGATOR_SHA": "b" * 40,
        "AGGREGATOR_SOURCE_SHA": "b" * 40,
        "SCOPE_SHA": "b" * 40,
        "SCOPE_SOURCE_SHA": "b" * 40,
        "BACKEND_CONTRACTS_SHA": "b" * 40,
        "BACKEND_CONTRACTS_SOURCE_SHA": "b" * 40,
        "BACKEND_FROZEN_SHA": "b" * 40,
        "BACKEND_FROZEN_SOURCE_SHA": "b" * 40,
        "WINDOWS_PACKAGING_SHA": "b" * 40,
        "WINDOWS_PACKAGING_SOURCE_SHA": "b" * 40,
    }
    for field, value in mutations.items():
        assert not verify({**baseline, field: value}).ok, field
    for field in baseline:
        candidate = dict(baseline)
        del candidate[field]
        assert not verify(candidate).ok, field
