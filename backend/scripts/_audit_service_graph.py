"""Read-only audit: service import graph + signals of god/coupling issues.

Exit code is 0 only if no NEW service-to-service cycles appear. The
two v0.9 cycles below are tracked as known technical debt
(lazy-import workarounds) and PASS the audit while still being
printed; anything outside the allowlist fails so release_audit.py
catches drift instead of silently rubber-stamping new debt.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
from collections import defaultdict

# v0.9 cycles intentionally left for v1.x cleanup. Each pair is a
# lazy-import workaround where service A's hot path needs B and B's
# cold path needs a pure helper from A. Adding a cycle outside this
# set fails the audit — fix the cycle (preferred) or add it here
# with the v1.x ticket / commit that introduced the regression.
KNOWN_CYCLES: set[frozenset[str]] = {
    frozenset({
        "app.services.exchange_rate_service",
        "app.services.fx_rate_provider",
    }),
    frozenset({
        "app.services.category_service",
        "app.services.spending_contract_service",
    }),
}


def main() -> int:  # noqa: C901 - one-shot read-only audit script; flat top-level driver, splitting wouldn't reduce branching
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
        return 0

    unique = {frozenset(c) for c in found}
    new_cycles = unique - KNOWN_CYCLES
    stale_allowlist = KNOWN_CYCLES - unique

    for c in sorted(unique, key=lambda s: sorted(s)):
        kind = "known" if c in KNOWN_CYCLES else "NEW"
        print(f"  cycle ({kind}):", " <-> ".join(sorted(c)))

    print()
    if stale_allowlist:
        print("=== Stale allowlist entries (cycle no longer present) ===")
        for c in sorted(stale_allowlist, key=lambda s: sorted(s)):
            print("  ", " <-> ".join(sorted(c)))
        print("  → remove the corresponding entry from KNOWN_CYCLES.")
        print()

    if new_cycles:
        print("=== NEW service-to-service cycles (not in KNOWN_CYCLES) ===")
        for c in sorted(new_cycles, key=lambda s: sorted(s)):
            print("  ", " <-> ".join(sorted(c)))
        print("  → break the cycle (preferred) or add it to KNOWN_CYCLES")
        print("    with the v1.x ticket / commit that introduced it.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
