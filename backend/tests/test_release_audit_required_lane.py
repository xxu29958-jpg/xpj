from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.parallel_safe


def test_release_audit_fails_closed_for_missing_or_gutted_required_lane(
    tmp_path: Path,
) -> None:
    mod = importlib.reload(importlib.import_module("release_audit"))
    filename = "_audit_pr_delta_metrics.py"

    missing = mod._required_lane_contract_failures(tmp_path, [])
    assert missing == [f"required release audit lane is missing or excluded: {filename}"]

    lane = tmp_path / filename
    lane.write_text(
        "def main():\n"
        "    evaluate_pr_delta_metrics({})\n"
        "    return 0\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="ascii",
    )
    gutted = mod._required_lane_contract_failures(
        tmp_path,
        [("pr-delta-metrics", filename)],
    )
    assert gutted == [
        "required release audit call is missing: "
        f"{filename}: evaluate_protected_pytest_memberships"
    ]

    lane.write_text(
        "def main():\n"
        "    evaluate_pr_delta_metrics({})\n"
        "    evaluate_protected_pytest_memberships({}, {})\n"
        "    return 0\n",
        encoding="ascii",
    )
    inert = mod._required_lane_contract_failures(
        tmp_path,
        [("pr-delta-metrics", filename)],
    )
    assert inert == [f"required release audit lane does not execute main(): {filename}"]

    lane.write_text(
        "def main():\n"
        "    evaluate_pr_delta_metrics({})\n"
        "    evaluate_protected_pytest_memberships({}, {})\n"
        "    return 0\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    if False:\n"
        "        main()\n",
        encoding="ascii",
    )
    nested_inert = mod._required_lane_contract_failures(
        tmp_path,
        [("pr-delta-metrics", filename)],
    )
    assert nested_inert == [
        f"required release audit lane does not execute main(): {filename}"
    ]
