"""Select existing journey consumers from their actual script dependencies."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
from functools import cache
from pathlib import Path

from scripts.ci_scope import changed_paths

ROOT = Path(__file__).resolve().parents[2]
ENTRY = "backend/scripts/planning_consumer_journey.py"
WORKFLOW = ".github/workflows/planning-consumer-journey.yml"
POLICY = {WORKFLOW, ENTRY, "backend/scripts/planning_journey_scope.py", "backend/scripts/planning_journey_results.py"}


def _imports(tree: ast.AST) -> set[str]:
    return {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("scripts.")
    } | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names if alias.name.startswith("scripts.")
    }


def _dependencies(modules: set[str], read_tree) -> set[str]:
    pending = list(modules)
    paths: set[str] = set()
    while pending:
        module = pending.pop()
        path = "backend/" + module.replace(".", "/") + ".py"
        if path in paths:
            continue
        paths.add(path)
        pending.extend(_imports(read_tree(path)))
    return paths


def _branch_group(node: ast.If) -> str | None:
    test = node.test
    if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
        and isinstance(test.left, ast.Attribute) and test.left.attr == "group"
        and isinstance(test.left.value, ast.Name) and test.left.value.id == "args"
        and isinstance(test.comparators[0], ast.Constant) and isinstance(test.comparators[0].value, str)):
        return test.comparators[0].value
    return None


def journey_dependencies(root: Path = ROOT, revision: str = "") -> dict[str, set[str]]:
    @cache
    def read_tree(path: str) -> ast.Module:
        source = subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=root).decode("utf-8-sig") if revision else (root / path).read_text(encoding="utf-8-sig")
        return ast.parse(source)

    tree = read_tree(ENTRY)
    argument = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
        and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--group")
    groups = ast.literal_eval(next(item.value for item in argument.keywords if item.arg == "choices"))
    if not groups or len(set(groups)) != len(groups) or any(not isinstance(group, str) for group in groups):
        raise ValueError("The actual journey entry must declare unique groups")
    # Top-level imports are loaded before every group starts, including shared
    # Android navigation, identity/recovery and the sealed database contract.
    common = set().union(*(_imports(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))))
    modules = {group: set(common) for group in groups}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and (group := _branch_group(node)) in modules:
            modules[group].update(_imports(ast.Module(body=node.body, type_ignores=[])))
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (isinstance(key, ast.Constant) and key.value in modules and isinstance(value, ast.Constant)
                    and isinstance(value.value, str) and value.value.startswith("scripts.") and ":" in value.value):
                    modules[key.value].add(value.value.split(":", 1)[0])
    return {group: _dependencies(imports, read_tree) | POLICY for group, imports in modules.items()}


def select_groups(paths: list[str], requested: str = "", *, root: Path = ROOT, base: str = "", head: str = "") -> dict:
    dependencies = journey_dependencies(root, head)
    if requested:
        if requested not in dependencies and requested != "cold-copy":
            raise ValueError(f"Unknown journey group: {requested}")
        return {"requested": requested, "selected": [requested], "reason": "explicit group"}
    if not paths:
        raise ValueError("Automatic journey selection has no changed paths")
    previous = journey_dependencies(root, base) if base else {}
    selected: set[str] = set()
    for path in paths:
        consumers = {group for graph in (previous, dependencies) for group, sources in graph.items() if path in sources}
        if consumers - dependencies.keys():
            raise ValueError(f"Removed journey groups need an explicit qualification disposition: {sorted(consumers - dependencies.keys())}")
        if not consumers and path.startswith("backend/scripts/") and ("journey" in path or "planning_notification_" in path):
            raise ValueError(f"Journey script has no proven consumer: {path}")
        selected.update(consumers)
    return {"requested": "automatic", "selected": sorted(selected), "paths": paths, "dependency_base": base, "dependency_head": head,
        "reason": "actual script consumers" if selected else "no journey harness input changed; product qualification is separate"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--source", required=True)
    parser.add_argument("--requested", default="")
    parser.add_argument("--installer-run-id", default="")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.event == "workflow_dispatch":
        if not args.requested:
            raise ValueError("Manual journey requires an explicit group")
        selection = select_groups([], args.requested)
    elif args.event in {"pull_request", "push"} and args.base:
        base = subprocess.check_output(["git", "merge-base", args.base, args.source], text=True).strip()
        selection = select_groups(changed_paths(args.base, args.source), base=base, head="HEAD")
    else:
        raise ValueError("Automatic journey requires a supported event and exact diff base")
    cold_copy = selection["selected"] == ["cold-copy"]
    if cold_copy and not args.installer_run_id.isdecimal():
        raise ValueError("cold-copy requires the exact candidate installer run")
    selection.update(checkout_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        source_sha=args.source, run_id=os.environ["GITHUB_RUN_ID"], run_attempt=os.environ["GITHUB_RUN_ATTEMPT"])
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / "selection.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write("matrix=" + json.dumps({"group": [] if cold_copy else selection["selected"]}) + "\n")
        output.write(f"consumers={str(bool(selection['selected']) and not cold_copy).lower()}\n")
        output.write(f"cold_copy={str(cold_copy).lower()}\n")
    print(json.dumps(selection, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
