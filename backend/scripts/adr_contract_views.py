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
STATUS_METADATA_START = "<!-- ADR_STATUS_METADATA_START -->"
STATUS_METADATA_END = "<!-- ADR_STATUS_METADATA_END -->"
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


@dataclass(frozen=True)
class EffectiveAdrState:
    """Current projection after accepted successor amendments."""

    current_scope: str
    implementation_status: str
    verification_status: str
    amendments: tuple[tuple[RegistryEntry, AdrRelation], ...]


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
        "entries": [_entry_json(registry, entry) for entry in registry.entries],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_status_table(registry: Registry) -> str:
    lines = [
        "| ADR | 决策状态 | 实现状态 | 验证状态 | 当前有效范围 | 关系 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in registry.entries:
        effective = _effective_state(registry, entry)
        link = f"../DECISIONS/{Path(entry.path).name}"
        lines.append(
            f"| [{entry.adr_id}]({link}) | {entry.decision_status} | "
            f"{effective.implementation_status} | {effective.verification_status} | "
            f"{effective.current_scope} | "
            f"{_relation_summary(entry.relations, effective.amendments)} |"
        )
    return "\n".join(lines)


def render_status_metadata(registry: Registry) -> str:
    return "\n".join(
        (
            f"- 组合审查日期: {registry.portfolio_reviewed_at}",
            f"- Review base: `{registry.code_baseline}` (pre-implementation main snapshot)",
            f"- Baseline scope: {registry.baseline_scope}",
        )
    )


def render_index_table(registry: Registry) -> str:
    lines = [
        "| # | 标题 | 一句话 | 状态 | 关系 |",
        "|---|---|---|---|---|",
    ]
    for entry in registry.entries:
        effective = _effective_state(registry, entry)
        filename = Path(entry.path).name
        state = (
            f"{entry.decision_status} / {effective.implementation_status} / "
            f"{effective.verification_status}"
        )
        lines.append(
            f"| [{entry.adr_id}]({filename}) | {entry.title} | {entry.summary} | "
            f"{state} | {_relation_summary(entry.relations, effective.amendments)} |"
        )
    return "\n".join(lines)


def render_dependency_graph(registry: Registry) -> str:
    lines = [
        "# ADR 依赖与演进图",
        "",
        "> 由 schema-v2 front matter、冻结 legacy identity baseline 与当前 calibration 生成；禁止手工编辑。",
        f"> 审查基线：`{registry.code_baseline}`；组合审查日期：{registry.portfolio_reviewed_at}。",
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
        STATUS_METADATA_START,
        STATUS_METADATA_END,
        render_status_metadata(registry),
    )
    status = replace_generated_block(
        status,
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


def _entry_json(registry: Registry, entry: RegistryEntry) -> dict[str, Any]:
    effective = _effective_state(registry, entry)
    payload = asdict(entry)
    payload["id"] = payload.pop("adr_id")
    payload["relations"] = [asdict(relation) for relation in entry.relations]
    payload["clause_ids"] = list(entry.clause_ids)
    payload["declared_current_scope"] = entry.current_scope
    payload["declared_implementation_status"] = entry.implementation_status
    payload["declared_verification_status"] = entry.verification_status
    payload["current_scope"] = effective.current_scope
    payload["implementation_status"] = effective.implementation_status
    payload["verification_status"] = effective.verification_status
    payload["effective_amendments"] = [
        {
            "source": source.adr_id,
            "scope": relation.scope,
            "implementation_status": _effective_state(
                registry, source
            ).implementation_status,
            "verification_status": _effective_state(
                registry, source
            ).verification_status,
        }
        for source, relation in effective.amendments
    ]
    return payload


def _effective_state(
    registry: Registry,
    entry: RegistryEntry,
    resolving: frozenset[str] = frozenset(),
) -> EffectiveAdrState:
    if entry.adr_id in resolving:
        raise RegistryError(
            f"effective ADR amendment cycle reached ADR-{entry.adr_id}"
        )
    next_resolving = resolving | {entry.adr_id}
    amendments = tuple(
        (source, relation)
        for source in registry.entries
        if source.decision_status == "accepted"
        for relation in source.relations
        if relation.kind == "amends" and relation.target == entry.adr_id
    )
    if not amendments:
        return EffectiveAdrState(
            current_scope=entry.current_scope,
            implementation_status=entry.implementation_status,
            verification_status=entry.verification_status,
            amendments=(),
        )
    amendment_states = tuple(
        (source, relation, _effective_state(registry, source, next_resolving))
        for source, relation in amendments
    )
    amendment_scope = "；".join(
        f"ADR-{source.adr_id} 后继修订（{relation.scope}）：{state.current_scope}"
        for source, relation, state in amendment_states
    )
    scope = (
        f"ADR-{entry.adr_id} 未被后继关系覆盖的 declared_current_scope："
        f"{entry.current_scope}；当前修订：{amendment_scope}"
    )
    implementation_order = {
        "nonconformant": 0,
        "not-started": 1,
        "implementing": 2,
        "partial": 3,
        "implemented": 4,
    }
    verification_order = {
        "failed": 0,
        "unverified": 1,
        "stale": 2,
        "verified": 3,
    }
    implementation_statuses = (entry.implementation_status,) + tuple(
        state.implementation_status for _, _, state in amendment_states
    )
    verification_statuses = (entry.verification_status,) + tuple(
        state.verification_status for _, _, state in amendment_states
    )
    return EffectiveAdrState(
        current_scope=scope,
        implementation_status=min(
            implementation_statuses,
            key=implementation_order.__getitem__,
        ),
        verification_status=min(
            verification_statuses,
            key=verification_order.__getitem__,
        ),
        amendments=amendments,
    )


def _relation_summary(
    relations: tuple[AdrRelation, ...],
    amendments: tuple[tuple[RegistryEntry, AdrRelation], ...] = (),
) -> str:
    summaries = [f"{item.kind} {item.target}" for item in relations]
    summaries.extend(f"amended-by {source.adr_id}" for source, _ in amendments)
    if not summaries:
        return "—"
    return "; ".join(summaries)
