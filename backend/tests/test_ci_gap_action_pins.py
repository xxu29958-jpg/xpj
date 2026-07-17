from __future__ import annotations

from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_audit as _load
from tests._infra.ci_gap_action_pins import (
    write_action_pin_mutations,
    write_action_pin_workflows,
    write_action_pin_yaml_shapes,
    write_composite_action_dependency,
)

pytestmark = pytest.mark.parallel_safe

_CHECKOUT = "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10"


def test_github_actions_require_reviewed_identity_and_commit(
    tmp_path: Path,
) -> None:
    mod = _load()
    workflows, mutations = write_action_pin_workflows(tmp_path)
    assert mod._github_external_uses_pin_violations(workflows) == []

    write_composite_action_dependency(workflows, "owner/composite-dependency@main")
    composite_violations = mod._github_external_uses_pin_violations(workflows)
    assert any(
        ".github/actions/local-check/action.yml" in item
        and "owner/composite-dependency@main" in item
        for item in composite_violations
    )
    write_composite_action_dependency(workflows, _CHECKOUT)

    write_action_pin_mutations(workflows, mutations)
    violations = mod._github_external_uses_pin_violations(workflows)
    assert len(violations) == len(mutations)
    for uses in mutations.values():
        assert any(uses in violation for violation in violations)

    write_action_pin_yaml_shapes(workflows)
    shape_violations = mod._github_external_uses_pin_violations(workflows)
    assert any("owner/quoted-action@v1.2.3" in item for item in shape_violations)
    assert any("owner/flow-action@main" in item for item in shape_violations)

    duplicate = workflows.parent / "actions" / "local-check" / "action.yaml"
    duplicate.write_text("name: duplicate\n", encoding="utf-8")
    metadata_violations = mod._github_external_uses_pin_violations(workflows)
    assert any(
        "local action must resolve to exactly one metadata file" in item
        for item in metadata_violations
    )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            "./ci/actions/local-check",
            "local action must live under the audited .github/actions tree",
        ),
        (
            "./.github/actions/../outside",
            "local action path must not traverse directories",
        ),
    ],
)
def test_local_actions_cannot_escape_the_recursively_audited_tree(
    tmp_path: Path,
    replacement: str,
    message: str,
) -> None:
    mod = _load()
    workflows, _mutations = write_action_pin_workflows(tmp_path)
    workflow = workflows / "ci.yml"
    original = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        original.replace("./.github/actions/local-check", replacement, 1),
        encoding="utf-8",
    )
    violations = mod._github_external_uses_pin_violations(workflows)
    assert any(message in item for item in violations)
