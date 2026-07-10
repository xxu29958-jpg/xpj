"""Deterministic JSON and Markdown views for the ADR contract registry."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from adr_contract_registry import (
    DECISIONS_DIR,
    REPO_ROOT,
    Registry,
    RegistryEntry,
    RegistryError,
)
from adr_contract_schema import AdrRelation

REGISTRY_PATH = REPO_ROOT / "docs" / "current" / "adr-registry.json"
STATUS_PATH = REPO_ROOT / "docs" / "current" / "ADR_STATUS.md"
INDEX_PATH = DECISIONS_DIR / "README.md"
GRAPH_PATH = REPO_ROOT / "docs" / "current" / "ADR_DEPENDENCY_GRAPH.md"

STATUS_START = "<!-- ADR_STATUS_TABLE_START -->"
STATUS_END = "<!-- ADR_STATUS_TABLE_END -->"
INDEX_START = "<!-- ADR_INDEX_TABLE_START -->"
INDEX_END = "<!-- ADR_INDEX_TABLE_END -->"
NEXT_ID_START = "<!-- ADR_NEXT_ID_START -->"
NEXT_ID_END = "<!-- ADR_NEXT_ID_END -->"


@dataclass(frozen=True)
class ViewPaths:
    """Filesystem locations for generated views."""

    registry: Path
    status: Path
    index: Path
    graph: Path
    repo_root: Path


DEFAULT_VIEW_PATHS = ViewPaths(
    registry=REGISTRY_PATH,
    status=STATUS_PATH,
    index=INDEX_PATH,
    graph=GRAPH_PATH,
    repo_root=REPO_ROOT,
)


def registry_json(registry: Registry) -> str:
    """Render the canonical machine interface deterministically."""

    payload = {
        "schema_version": registry.schema_version,
        "front_matter_schema_version": registry.front_matter_schema_version,
        "portfolio_reviewed_at": registry.portfolio_reviewed_at,
        "code_baseline": registry.code_baseline,
        "bootstrap_base_commit": registry.bootstrap_base_commit,
        "baseline_scope": registry.baseline_scope,
        "entries": [_entry_json(entry) for entry in registry.entries],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_status_table(registry: Registry) -> str:
    lines = [
        "| ADR | 决策状态 | 实现状态 | 验证状态 | 当前有效范围 | 关系 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in registry.entries:
        link = f"../DECISIONS/{Path(entry.path).name}"
        lines.append(
            f"| [{entry.adr_id}]({link}) | {entry.decision_status} | "
            f"{entry.implementation_status} | {entry.verification_status} | "
            f"{entry.current_scope} | {_relation_summary(entry.relations)} |"
        )
    return "\n".join(lines)


def render_index_table(registry: Registry) -> str:
    lines = [
        "| # | 标题 | 一句话 | 状态 | 关系 |",
        "|---|---|---|---|---|",
    ]
    for entry in registry.entries:
        filename = Path(entry.path).name
        state = (
            f"{entry.decision_status} / {entry.implementation_status} / "
            f"{entry.verification_status}"
        )
        lines.append(
            f"| [{entry.adr_id}]({filename}) | {entry.title} | {entry.summary} | "
            f"{state} | {_relation_summary(entry.relations)} |"
        )
    return "\n".join(lines)


def render_dependency_graph(registry: Registry) -> str:
    lines = [
        "# ADR 依赖与演进图",
        "",
        "> 由 schema-v2 front matter、冻结 legacy identity baseline 与当前 calibration 生成；禁止手工编辑。",
        f"> 代码核对基线：`{registry.code_baseline}`；组合审查日期：{registry.portfolio_reviewed_at}。",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    related_nodes: set[str] = set()
    for entry in registry.entries:
        for relation in entry.relations:
            related_nodes.update({entry.adr_id, relation.target})
            label = relation.kind.replace("-", " ")
            lines.append(
                f'  A{entry.adr_id}["{entry.adr_id}"] -->|{label}| '
                f'A{relation.target}["{relation.target}"]'
            )
    if not related_nodes:
        lines.append('  EMPTY["暂无显式关系"]')
    lines.extend(["```", "", "## 未迁移 legacy ADR", ""])
    legacy = [
        entry.adr_id
        for entry in registry.entries
        if entry.source_kind == "legacy-baseline"
    ]
    lines.append(
        "以下 ADR 仍由内容哈希 baseline 冻结；修改时必须迁移相关 front matter/条款：\n"
        + ", ".join(legacy)
        + "。"
    )
    lines.extend(
        [
            "",
            "## 显式关系",
            "",
            "| Source | Relation | Target | Scope |",
            "| --- | --- | --- | --- |",
        ]
    )
    for entry in registry.entries:
        for relation in entry.relations:
            lines.append(
                f"| {entry.adr_id} | {relation.kind} | {relation.target} | {relation.scope} |"
            )
    if not any(entry.relations for entry in registry.entries):
        lines.append("| — | — | — | 尚无显式关系 |")
    return "\n".join(lines) + "\n"


def replace_generated_block(text: str, start: str, end: str, content: str) -> str:
    """Replace one uniquely delimited generated block."""

    if text.count(start) != 1 or text.count(end) != 1:
        raise RegistryError(f"generated view requires exactly one {start}/{end} pair")
    prefix, remainder = text.split(start, 1)
    _, suffix = remainder.split(end, 1)
    return f"{prefix}{start}\n{content.rstrip()}\n{end}{suffix}"


def expected_views(
    registry: Registry, *, paths: ViewPaths = DEFAULT_VIEW_PATHS
) -> dict[Path, str]:
    """Return every generated artifact/view expected in the worktree."""

    status = replace_generated_block(
        paths.status.read_text(encoding="utf-8"),
        STATUS_START,
        STATUS_END,
        render_status_table(registry),
    )
    index = replace_generated_block(
        paths.index.read_text(encoding="utf-8"),
        INDEX_START,
        INDEX_END,
        render_index_table(registry),
    )
    next_id = replace_generated_block(
        index,
        NEXT_ID_START,
        NEXT_ID_END,
        f"下一编号 `{_next_adr_id(registry)}`。",
    )
    return {
        paths.registry: registry_json(registry),
        paths.status: status,
        paths.index: next_id,
        paths.graph: render_dependency_graph(registry),
    }


def stale_view_errors(
    registry: Registry, *, paths: ViewPaths = DEFAULT_VIEW_PATHS
) -> list[str]:
    errors: list[str] = []
    for path, expected in expected_views(registry, paths=paths).items():
        if not path.exists():
            errors.append(
                f"generated ADR view is missing: {_display_path(path, paths.repo_root)}"
            )
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(
                f"generated ADR view is stale: {_display_path(path, paths.repo_root)}"
            )
    return errors


def write_views(
    registry: Registry, *, paths: ViewPaths = DEFAULT_VIEW_PATHS
) -> None:
    """Write deterministic views; intended only for the explicit render command."""

    for path, content in expected_views(registry, paths=paths).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def _next_adr_id(registry: Registry) -> str:
    return f"{max(int(entry.adr_id) for entry in registry.entries) + 1:04d}"


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _entry_json(entry: RegistryEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["id"] = payload.pop("adr_id")
    payload["relations"] = [asdict(relation) for relation in entry.relations]
    payload["clause_ids"] = list(entry.clause_ids)
    return payload


def _relation_summary(relations: tuple[AdrRelation, ...]) -> str:
    if not relations:
        return "—"
    return "; ".join(f"{item.kind} {item.target}" for item in relations)
