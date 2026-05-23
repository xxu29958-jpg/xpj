"""Read-only audit: service import graph + signals of god/coupling issues.

Two cycle detection lanes:

- **Package-level** (``app.services.X`` vs ``app.services.Y``): catches
  service-to-service architectural cycles like the
  ``expense_service ↔ receipt_item_service`` and
  ``exchange_rate_service ↔ fx_rate_provider`` ones broken in 2026-05.
- **Module-level** (full ``app.services.X._submodule`` path): catches
  intra-package cycles like ``csv_import_batch_service._csv_io ↔
  _lifecycle``. These are usually lazy-import workarounds inside a
  service's own subfiles; the gate refuses to wave them through.

Both lanes share KNOWN_CYCLES. New cycles in either lane → exit 1.
Stale entries (allowlist names a cycle that's no longer there) →
exit 1. The list cannot rot into "polite way to live with debt".
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
from collections import defaultdict

# Currently empty. New cycles fail the audit immediately — fix the
# cycle (preferred) or, only when a release deadline is genuinely
# tighter than the refactor, add it here with the ticket/commit that
# introduced it. Stale entries (cycle listed here but no longer
# present in the code) also fail, so this list cannot rot.
KNOWN_CYCLES: set[frozenset[str]] = set()


def main() -> int:  # noqa: C901 - one-shot read-only audit script; flat top-level driver, splitting wouldn't reduce branching
    base = pathlib.Path("app/services")
    # Cross-package graph: src/target collapsed to ``app.services.X``
    # for "is service A's import surface coupled to service B's?"
    graph: dict[str, set[str]] = defaultdict(set)
    rev_graph: dict[str, set[str]] = defaultdict(set)
    # Full-module graph: ``app.services.X._sub`` kept distinct from
    # ``app.services.X._other`` so intra-package cycles are visible.
    module_graph: dict[str, set[str]] = defaultdict(set)

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
                # Module graph keeps the full path on both sides; even
                # imports of a sibling subfile are recorded.
                if target != me:
                    module_graph[me].add(target)
                # Package-level edge drops sub-module suffixes.
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
    print("=== Cycle detection (package + module level) ===")

    def detect_cycles(g: dict[str, set[str]]) -> set[frozenset[str]]:
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
            for nxt in g.get(node, ()):
                dfs(nxt)
            in_stack.discard(node)
            stack_list.pop()

        for n in list(g.keys()):
            dfs(n)
        return {frozenset(c) for c in found}

    package_cycles = detect_cycles(graph)
    module_cycles = detect_cycles(module_graph)
    # Module cycles whose every node collapses to a single package are
    # intra-package; package-level cycles are everything else. We
    # report both but the failure mode is the same.
    found_all = package_cycles | module_cycles

    new_cycles = found_all - KNOWN_CYCLES
    stale_allowlist = KNOWN_CYCLES - found_all

    # NOTE: don't return early on "no cycles found" — that path used to
    # bypass the stale_allowlist check, letting KNOWN_CYCLES rot
    # silently when the cycle it tracked was finally fixed. Computing
    # both sets first means stale entries always fail, even in the
    # clean-graph case.
    if not found_all:
        print("  No cycles found (package or module level).")
    else:
        for c in sorted(found_all, key=lambda s: sorted(s)):
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

    if new_cycles or stale_allowlist:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
