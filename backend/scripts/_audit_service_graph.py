"""Read-only audit: service import graph + signals of god/coupling issues."""

from __future__ import annotations

import ast
import os
import pathlib
from collections import defaultdict


def main() -> None:
    base = pathlib.Path("app/services")
    graph: dict[str, set[str]] = defaultdict(set)
    rev_graph: dict[str, set[str]] = defaultdict(set)

    for p in base.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rel = str(p).replace(os.sep, "/")
        me = rel.removesuffix(".py").replace("/", ".")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.services."):
                target = node.module
                if target.split(".")[2] != me.split(".")[2]:
                    graph[me].add(target)
                    rev_graph[target].add(me)

    print("=== Service-to-service fanout (top 15 outgoing) ===")
    for src, deps in sorted(graph.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"  {len(deps):2d}  {src}")
        for d in sorted(deps):
            print(f"        -> {d}")

    print()
    print("=== Reverse fanout (top 12 most-imported services) ===")
    for tgt, importers in sorted(rev_graph.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"  {len(importers):2d}  {tgt}")

    print()
    print("=== Cycle detection ===")
    seen: dict[str, int] = {}
    in_stack: set[str] = set()
    stack_list: list[str] = []
    found: list[list[str]] = []

    def dfs(node: str) -> None:
        if node in in_stack:
            cycle_start = stack_list.index(node)
            found.append(stack_list[cycle_start:] + [node])
            return
        if node in seen:
            return
        seen[node] = 1
        in_stack.add(node)
        stack_list.append(node)
        for nxt in graph.get(node, ()):
            dfs(nxt)
        in_stack.discard(node)
        stack_list.pop()

    for n in list(graph.keys()):
        dfs(n)

    if not found:
        print("  No service-to-service cycles found.")
    else:
        unique = {tuple(sorted(set(c))) for c in found}
        for c in unique:
            print("  cycle:", " <-> ".join(c))


if __name__ == "__main__":
    main()
