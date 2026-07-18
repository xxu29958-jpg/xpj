from __future__ import annotations

from pathlib import Path


def write_action_pin_workflows(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    pinned = "a" * 40
    (workflows / "ci.yml").write_text(
        f"""
name: CI
jobs:
  checks:
    steps:
      # uses: actions/comment-only@v6.0.3
      - uses: actions/checkout@{pinned} # pinned release
      - uses: ./.github/actions/local-check
      - run: |
          Write-Host "uses: actions/prose-only@release"
""",
        encoding="utf-8",
    )
    composite = workflows.parent / "actions" / "local-check" / "action.yml"
    composite.parent.mkdir(parents=True)
    composite.write_text(
        f"""
name: local check
runs:
  using: composite
  steps:
    - uses: actions/checkout@{pinned}
""",
        encoding="utf-8",
    )
    mutations = {
        "semver.yaml": "actions/checkout@v6.0.3",
        "release.yml": "owner/action@release",
        "main.yml": "owner/action@main",
        "short-sha.yml": f"owner/action@{pinned[:-1]}",
    }
    return workflows, mutations


def write_action_pin_mutations(workflows: Path, mutations: dict[str, str]) -> None:
    for name, uses in mutations.items():
        (workflows / name).write_text(
            f"""
name: mutation
jobs:
  checks:
    steps:
      - uses: {uses}
""",
            encoding="utf-8",
        )


def write_composite_action_dependency(workflows: Path, uses: str) -> None:
    (workflows.parent / "actions" / "local-check" / "action.yml").write_text(
        f"""
name: local check
runs:
  using: composite
  steps:
    - uses: {uses}
""",
        encoding="utf-8",
    )


def write_action_pin_yaml_shapes(workflows: Path) -> None:
    (workflows / "yaml-shapes.yml").write_text(
        """
name: shape mutations
jobs:
  quoted:
    steps:
      - 'uses' : owner/quoted-action@v1.2.3
      - { uses : owner/flow-action@main, name: flow }
      - "us\\u0065s": owner/escaped-key@release
""",
        encoding="utf-8",
    )
