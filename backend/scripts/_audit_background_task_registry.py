"""Release gate for background-task handler registry ownership."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = BACKEND_ROOT / "app" / "services" / "background_task_service.py"
REGISTRY_PATH = BACKEND_ROOT / "app" / "services" / "background_task_registry.py"


def _module_registry_assignments(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for statement in tree.body:
        value: ast.AST | None = None
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            value = statement.value
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            value = statement.value
            targets = [statement.target]
        if not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Name) or value.func.id != "TaskHandlerRegistry":
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def main() -> int:
    failures: list[str] = []
    service_text = SERVICE_PATH.read_text(encoding="utf-8")
    service_tree = ast.parse(service_text, filename=str(SERVICE_PATH))
    registry_text = REGISTRY_PATH.read_text(encoding="utf-8")

    assignments = _module_registry_assignments(service_tree)
    if assignments:
        failures.append(
            "background_task_service must not keep module-level "
            f"TaskHandlerRegistry instances: {', '.join(assignments)}"
        )
    if "_default_handler_registry" in service_text:
        failures.append("_default_handler_registry must not return")
    if "replace_registered_handlers_for_testing" in service_text:
        failures.append("tests must use isolated ContextVar registries, not global replacement")
    if "def runtime_handler_registry" not in registry_text:
        failures.append("runtime_handler_registry catalog is missing")

    if failures:
        print("FAIL: background task registry is not isolated:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PASS: background task runtime handlers use explicit catalog + test isolation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
