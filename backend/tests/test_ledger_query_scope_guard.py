from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
SCAN_ROOTS = (APP_ROOT / "routes", APP_ROOT / "services")

LEDGER_SCOPED_MODELS = {
    "CategoryRule",
    "DuplicateIgnore",
    "Expense",
    "RecurringItem",
}
SCOPE_COLUMNS = {"tenant_id", "ledger_id"}
SCOPE_HELPERS = {"add_ledger_scope", "ledger_filter", "ledger_scoped_select"}
ORM_QUERY_FUNCTIONS = {"delete", "select", "update"}


@dataclass(frozen=True)
class ScopeExemption:
    path: str
    function: str
    model: str
    occurrences: int
    reason: str


@dataclass(frozen=True)
class QuerySite:
    path: str
    function: str
    line: int
    model: str
    snippet: str


EXEMPTIONS = (
    ScopeExemption(
        path="services/owner_console_service.py",
        function="get_index_vm",
        model="Expense",
        occurrences=2,
        reason=(
            "Owner Console index is loopback-only and intentionally shows "
            "global pending/confirmed counters before a ledger is selected."
        ),
    ),
)


def test_ledger_scoped_orm_queries_are_explicitly_filtered() -> None:
    unscoped_sites = list(_find_unscoped_query_sites())
    remaining, used_counts = _apply_exemptions(unscoped_sites)
    stale_exemptions = [
        exemption
        for exemption in EXEMPTIONS
        if used_counts.get(_exemption_key(exemption), 0) != exemption.occurrences
    ]

    messages: list[str] = []
    if remaining:
        messages.append("Unscoped ledger-scoped ORM queries:")
        messages.extend(_format_site(site) for site in remaining)
        messages.append(
            "Add an explicit Model.tenant_id/ledger_id predicate, or use "
            "app.ledger_scope.ledger_scoped_select/add_ledger_scope. If the "
            "query is intentionally global, add a narrow EXEMPTIONS entry "
            "with an occurrence count and reason."
        )
    if stale_exemptions:
        messages.append("Stale or mismatched ledger query exemptions:")
        messages.extend(
            f"- {item.path}:{item.function} model={item.model} "
            f"expected={item.occurrences} reason={item.reason}"
            for item in stale_exemptions
        )

    assert not messages, "\n".join(messages)


def _find_unscoped_query_sites() -> list[QuerySite]:
    sites: list[QuerySite] = []
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for function in _iter_functions(tree):
            function_name = function.name
            for statement in _iter_query_statements(function):
                for model in sorted(_models_referenced(statement)):
                    if _has_ledger_scope(statement, model):
                        continue
                    sites.append(
                        QuerySite(
                            path=_relative_app_path(path),
                            function=function_name,
                            line=statement.lineno,
                            model=model,
                            snippet=_snippet(text, statement),
                        )
                    )
    return sites


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend(path for path in root.glob("*.py") if path.name != "__init__.py")
    return sorted(files)


def _iter_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _iter_query_statements(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Return))
        and _contains_orm_query(node)
    ]


def _contains_orm_query(node: ast.AST) -> bool:
    return any(_is_orm_query_call(child) for child in ast.walk(node))


def _is_orm_query_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _call_name(node.func) in ORM_QUERY_FUNCTIONS:
        return True
    return _is_session_get_for_scoped_model(node)


def _is_session_get_for_scoped_model(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return False
    return bool(node.args and _model_name(node.args[0]) in LEDGER_SCOPED_MODELS)


def _models_referenced(node: ast.AST) -> set[str]:
    models: set[str] = set()
    for child in ast.walk(node):
        model_name = _model_name(child)
        if model_name in LEDGER_SCOPED_MODELS:
            models.add(model_name)
    return models


def _model_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id
    return None


def _has_ledger_scope(node: ast.AST, model: str) -> bool:
    for child in ast.walk(node):
        if _helper_scopes_model(child, model):
            return True
        if _scope_column_compared(child, model):
            return True
        if _scope_column_method_called(child, model):
            return True
    return False


def _helper_scopes_model(node: ast.AST, model: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _call_name(node.func) not in SCOPE_HELPERS:
        return False
    return any(_model_name(arg) == model for arg in node.args)


def _scope_column_compared(node: ast.AST, model: str) -> bool:
    if not isinstance(node, ast.Compare):
        return False
    operands = [node.left, *node.comparators]
    return any(_is_scope_column(operand, model) for operand in operands)


def _scope_column_method_called(node: ast.AST, model: str) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    return _is_scope_column(node.func.value, model)


def _is_scope_column(node: ast.AST, model: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in SCOPE_COLUMNS
        and isinstance(node.value, ast.Name)
        and node.value.id == model
    )


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _apply_exemptions(
    sites: list[QuerySite],
) -> tuple[list[QuerySite], dict[tuple[str, str, str], int]]:
    allowed = {_exemption_key(exemption): exemption for exemption in EXEMPTIONS}
    used_counts = {key: 0 for key in allowed}
    remaining: list[QuerySite] = []
    for site in sites:
        key = _site_key(site)
        exemption = allowed.get(key)
        if exemption is None or used_counts[key] >= exemption.occurrences:
            remaining.append(site)
            continue
        used_counts[key] += 1
    return remaining, used_counts


def _exemption_key(exemption: ScopeExemption) -> tuple[str, str, str]:
    return (exemption.path, exemption.function, exemption.model)


def _site_key(site: QuerySite) -> tuple[str, str, str]:
    return (site.path, site.function, site.model)


def _format_site(site: QuerySite) -> str:
    return (
        f"- {site.path}:{site.line} in {site.function} "
        f"model={site.model}: {site.snippet}"
    )


def _relative_app_path(path: Path) -> str:
    return path.relative_to(APP_ROOT).as_posix()


def _snippet(text: str, node: ast.AST) -> str:
    segment = ast.get_source_segment(text, node) or ""
    line = segment.strip().splitlines()[0] if segment.strip() else type(node).__name__
    return line[:140]
