"""Read-only codebase audit. Walks app/, scripts/, tests/ and reports symptoms
across 7 dimensions (A-G). Writes nothing to the codebase."""

from __future__ import annotations

import ast
import contextlib
import os
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(".")
APP = pathlib.Path("app")
TESTS = pathlib.Path("tests")
SCRIPTS = pathlib.Path("scripts")


def walk(*roots: pathlib.Path):
    for r in roots:
        for p in r.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            yield p


def line_count(p: pathlib.Path) -> int:
    try:
        return sum(1 for _ in p.open(encoding="utf-8"))
    except Exception:
        return 0


def parse(p: pathlib.Path) -> ast.Module | None:
    try:
        return ast.parse(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _type_checking_import_lines(tree: ast.Module) -> set[int]:
    """Line numbers of imports nested under an ``if TYPE_CHECKING:`` block.

    These imports never execute at runtime, so they cannot violate
    "routes 直连 models" — the import only exists for annotation lookup
    by static type checkers.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_type_checking_test(node.test):
            continue
        for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(inner, (ast.ImportFrom, ast.Import)):
                lines.add(inner.lineno)
    return lines


def _suppressed_lines(p: pathlib.Path, code: str) -> set[int]:
    """Lines carrying ``# noqa: <code>`` (or ``noqa:<code>``)."""
    out: set[int] = set()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return out
    needle_a = f"noqa: {code}"
    needle_b = f"noqa:{code}"
    for i, line in enumerate(text.splitlines(), start=1):
        if needle_a in line or needle_b in line:
            out.add(i)
    return out


# -----------------------------------------------------------------------------
# A. SIZE & DISTRIBUTION
# -----------------------------------------------------------------------------

def audit_file_loc():
    rows = [(p, line_count(p)) for p in walk(APP, SCRIPTS, TESTS)]
    rows.sort(key=lambda r: -r[1])
    print("== A1. File LOC (top 30) ==")
    for p, n in rows[:30]:
        print(f"  {n:5d}  {p}")
    print()
    print("== A2. Files > 500 LOC ==")
    for p, n in rows:
        if n > 500:
            print(f"  {n:5d}  {p}")
    print()


def audit_surface_area():
    rows: list[tuple[pathlib.Path, int, int]] = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        defs = sum(1 for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        classes = sum(1 for n in tree.body if isinstance(n, ast.ClassDef))
        rows.append((p, defs, classes))
    rows.sort(key=lambda r: -(r[1] + r[2]))
    print("== A3. Module surface area (top 30 by def+class count) ==")
    for p, d, c in rows[:30]:
        print(f"  {d+c:3d} ({d}def {c}cls)  {p}")
    print()


def audit_long_functions():
    items: list[tuple[pathlib.Path, int, int, str]] = []
    for p in walk(APP, SCRIPTS, TESTS):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", None) or start
                length = end - start
                if length >= 80:
                    items.append((p, start, length, node.name))
    items.sort(key=lambda r: -r[2])
    print(f"== A4. Functions >= 80 LOC ({len(items)}) ==")
    for p, ln, length, name in items[:40]:
        print(f"  {length:4d}L  {p}:{ln}  {name}")
    print()


def _max_depth(node, current=0):
    depth = current
    body = []
    for attr in ("body", "orelse", "finalbody"):
        body.extend(getattr(node, attr, []) or [])
    for child in body:
        if isinstance(child, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.With, ast.AsyncWith, ast.Try, ast.TryStar)):
            depth = max(depth, _max_depth(child, current + 1))
        else:
            depth = max(depth, _max_depth(child, current))
    return depth


def audit_nesting_depth():
    items: list[tuple[pathlib.Path, int, int, str]] = []
    for p in walk(APP, SCRIPTS, TESTS):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                d = _max_depth(node)
                if d >= 5:
                    items.append((p, node.lineno, d, node.name))
    items.sort(key=lambda r: -r[2])
    print(f"== A5. Functions with nesting depth >= 5 ({len(items)}) ==")
    for p, ln, d, name in items[:40]:
        print(f"  depth={d}  {p}:{ln}  {name}")
    print()


def audit_directory_density():
    counts: dict[pathlib.Path, int] = defaultdict(int)
    for p in walk(APP):
        counts[p.parent] += 1
    print("== A6. Files per directory (sorted, top 15) ==")
    for d, c in sorted(counts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c:3d}  {d}")
    print()


# -----------------------------------------------------------------------------
# B. STRUCTURE & COUPLING
# -----------------------------------------------------------------------------

def audit_import_graph_and_cycles():
    graph, rev = _build_app_import_graph()
    _print_most_imported_modules(rev)
    sccs = _find_import_sccs(graph)
    print(f"== B2. Import cycles ({len(sccs)} SCC with >1 member) ==")
    for s in sccs:
        print(f"  {' <-> '.join(sorted(s))}")
    print()


def _build_app_import_graph() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    # Module-to-module import graph (only app.*)
    graph: dict[str, set[str]] = defaultdict(set)
    rev: dict[str, set[str]] = defaultdict(set)
    for p in walk(APP):
        if p.name == "__init__.py":
            continue
        tree = parse(p)
        if not tree:
            continue
        rel = str(p).replace(os.sep, "/").removesuffix(".py")
        me = rel.replace("/", ".")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                graph[me].add(node.module)
                rev[node.module].add(me)
    return graph, rev


def _print_most_imported_modules(rev: dict[str, set[str]]) -> None:
    print("== B1. Most-imported app modules (>= 8 importers) ==")
    for m, imps in sorted(rev.items(), key=lambda x: -len(x[1])):
        if len(imps) >= 8:
            print(f"  {len(imps):3d}  {m}")
    print()


def _find_import_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    # Tarjan SCC cycle detection.
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str):
        index[v] = index_counter[0]
        low[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(comp)

    sys.setrecursionlimit(5000)
    for node in list(graph.keys()):
        if node not in index:
            strongconnect(node)
    return sccs


def audit_layer_violations():
    """Routes (presentation) directly importing models or SQLAlchemy session/engine
    instead of going through a service. Inverted-layer hints.

    Imports nested under ``if TYPE_CHECKING:`` are skipped — they exist
    only for static type checking and never execute at runtime, so the
    layer boundary is not actually crossed.
    """
    items: list[tuple[pathlib.Path, int, str]] = []
    for p in walk(APP / "routes"):
        tree = parse(p)
        if not tree:
            continue
        type_checking_lines = _type_checking_import_lines(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.lineno in type_checking_lines:
                    continue
                m = node.module
                if m == "app.models" or m.startswith("app.models.") or m == "app.database" or m.startswith("app.database."):
                    items.append((p, node.lineno, f"imports {m}"))
    print(f"== B3. Route modules importing models / database directly ({len(items)}) ==")
    by_file: dict[pathlib.Path, list[tuple[int, str]]] = defaultdict(list)
    for p, ln, msg in items:
        by_file[p].append((ln, msg))
    for p, locs in sorted(by_file.items(), key=lambda x: -len(x[1]))[:30]:
        print(f"  {len(locs):3d}  {p}")
        for ln, msg in locs[:3]:
            print(f"          L{ln} {msg}")
    print()


def audit_sql_in_routes_or_services():
    """Routes / non-database services that hand-craft SQL strings (abstraction
    leak — presentation/business should call repository, not SQL)."""
    rx_sql = re.compile(r"\b(SELECT |INSERT |UPDATE |DELETE FROM|CREATE INDEX|CREATE TABLE|ALTER TABLE|PRAGMA )", re.IGNORECASE)
    items: list[tuple[pathlib.Path, int, str]] = []
    for p in walk(APP):
        if p.parts[:2] == ("app", "database"):
            continue  # SQL is expected here
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "text(" in line and rx_sql.search(line):
                items.append((p, i, line.strip()[:90]))
    print(f"== B4. SQL string literals outside app/database/ ({len(items)} lines) ==")
    by_file = defaultdict(list)
    for p, ln, line in items:
        by_file[p].append((ln, line))
    for p, locs in sorted(by_file.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"  {len(locs):3d}  {p}")
        for ln, line in locs[:2]:
            print(f"          L{ln} {line}")
    print()


def audit_import_star():
    items = []
    for p in walk(APP, SCRIPTS, TESTS):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("from ") and s.endswith(" import *"):
                items.append((p, i, s))
    print(f"== B5. `from X import *` ({len(items)}) ==")
    for p, ln, s in items:
        print(f"  {p}:{ln}  {s}")
    print()


# -----------------------------------------------------------------------------
# C. RESPONSIBILITY & ABSTRACTION
# -----------------------------------------------------------------------------

def audit_naming_smells():
    """Classes / functions whose name contains And/Or/Manager/Helper/Util."""
    rx = re.compile(r"\b(And|Or|Manager|Helper|Util|Misc)\b")
    items = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and rx.search(node.name)
            ):
                items.append((p, node.lineno, node.name))
    print(f"== C1. Smelly names (And/Or/Manager/Helper/Util) ({len(items)}) ==")
    for p, ln, name in items[:40]:
        print(f"  {p}:{ln}  {name}")
    print()


def audit_no_underscore_split():
    """Modules where everything is public — no `_internal` symbols at all,
    despite > 8 module-level defs."""
    items = []
    for p in walk(APP / "services"):
        if p.name == "__init__.py":
            continue
        tree = parse(p)
        if not tree:
            continue
        public = []
        private = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                (private if n.name.startswith("_") else public).append(n.name)
        if len(public) > 8 and not private:
            items.append((p, len(public)))
    print(f"== C2. Service modules with >8 public, 0 private (no internal boundary) ({len(items)}) ==")
    for p, n in items:
        print(f"  {n:3d}pub  {p}")
    print()


# -----------------------------------------------------------------------------
# D. DATA FLOW & STATE
# -----------------------------------------------------------------------------

def audit_globals_and_module_state():
    g_writes = []
    mod_mutable = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        # module-level mutable: list/dict/set literal, defaultdict(), {}, []
        for n in tree.body:
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        val = n.value
                        if isinstance(val, (ast.List, ast.Dict, ast.Set)):
                            mod_mutable.append((p, n.lineno, t.id, type(val).__name__))
                        elif isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id in {"list", "dict", "set", "defaultdict"}:
                            mod_mutable.append((p, n.lineno, t.id, val.func.id + "()"))
        # global writes
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                for name in node.names:
                    g_writes.append((p, node.lineno, name))
    print(f"== D1. `global` keyword usage ({len(g_writes)}) ==")
    for p, ln, n in g_writes:
        print(f"  {p}:{ln}  global {n}")
    print()
    print("== D2. Module-level mutable state (excluding __all__) ==")
    for p, ln, name, kind in mod_mutable:
        if name == "__all__":
            continue
        print(f"  {p}:{ln}  {name} ({kind})")
    print()


def audit_lru_cache_singletons():
    items = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    src = ast.unparse(dec)
                    if "cache" in src.lower():
                        items.append((p, node.lineno, node.name, src))
    print(f"== D3. Cached singletons (@cache/@lru_cache) ({len(items)}) ==")
    for p, ln, name, dec in items:
        print(f"  {p}:{ln}  @{dec}  {name}")
    print()


# -----------------------------------------------------------------------------
# E. CONTRACT
# -----------------------------------------------------------------------------

def audit_type_hint_coverage():
    total_fns = 0
    annotated = 0
    fully = 0
    unannotated_long = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_fns += 1
                has_ret = node.returns is not None
                has_args = all(
                    a.annotation is not None
                    for a in (node.args.args + node.args.kwonlyargs + node.args.posonlyargs)
                    if a.arg not in {"self", "cls"}
                )
                if has_ret or has_args:
                    annotated += 1
                if has_ret and has_args:
                    fully += 1
                if not has_ret and not has_args:
                    length = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno
                    if length > 20:
                        unannotated_long.append((p, node.lineno, length, node.name))
    pct_any = (annotated / total_fns * 100) if total_fns else 0
    pct_full = (fully / total_fns * 100) if total_fns else 0
    print("== E1. Type-hint coverage ==")
    print(f"  total functions: {total_fns}")
    print(f"  any annotation:  {annotated} ({pct_any:.1f}%)")
    print(f"  fully annotated: {fully} ({pct_full:.1f}%)")
    print(f"  unannotated, >20 LOC: {len(unannotated_long)}")
    for p, ln, length, name in sorted(unannotated_long, key=lambda r: -r[2])[:15]:
        print(f"    {length:3d}L  {p}:{ln}  {name}")
    print()


def audit_deep_arg_dicts():
    """Functions with `dict[str, dict[...]]` or `Dict[str, Dict[...]]` annotations,
    or signatures with `**kwargs` and `Any`."""
    rx = re.compile(r"(dict|Dict|Mapping)\s*\[\s*(?:str|Any)\s*,\s*(?:dict|Dict|Mapping|Any)")
    items = []
    for p in walk(APP):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "def " in line and rx.search(line):
                items.append((p, i, line.strip()[:120]))
    print(f"== E2. Nested-dict argument signatures ({len(items)}) ==")
    for p, ln, line in items[:30]:
        print(f"  {p}:{ln}  {line}")
    print()


def audit_return_type_inconsistency():
    """Functions that have both `return None` and `return <value>` paths."""
    items = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_value_return = False
                has_bare_return = False
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return):
                        if sub.value is None or (isinstance(sub.value, ast.Constant) and sub.value.value is None):
                            has_bare_return = True
                        else:
                            has_value_return = True
                if has_value_return and has_bare_return:
                    items.append((p, node.lineno, node.name))
    print(f"== E3. Functions with mixed `return X` and `return None/return` ({len(items)}) ==")
    for p, ln, name in items[:40]:
        print(f"  {p}:{ln}  {name}")
    print()


# -----------------------------------------------------------------------------
# F. ERROR HANDLING
# -----------------------------------------------------------------------------

def audit_bare_except():
    bare = []
    broad = []
    swallow = []
    for p in walk(APP, SCRIPTS, TESTS):
        tree = parse(p)
        if not tree:
            continue
        # Lines carrying `# noqa: BLE001` are intentional broad catches
        # (graceful degradation paths the linter accepts); skipping them
        # here keeps the audit signal focused on accidental swallows.
        ble001_lines = _suppressed_lines(p, "BLE001")
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    bare.append((p, node.lineno))
                else:
                    t = ast.unparse(node.type)
                    if t in {"Exception", "BaseException"} and node.lineno not in ble001_lines:
                        broad.append((p, node.lineno, t))
                # Swallowed (body is `pass` or just `...`)
                body = node.body
                if (
                    len(body) == 1
                    and isinstance(body[0], (ast.Pass, ast.Expr))
                    and (
                        isinstance(body[0], ast.Pass)
                        or (
                            isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and body[0].value.value is ...
                        )
                    )
                    and node.lineno not in ble001_lines
                ):
                    swallow.append((p, node.lineno))
    print(f"== F1. Bare `except:` ({len(bare)}) ==")
    for p, ln in bare:
        print(f"  {p}:{ln}")
    print()
    print(f"== F2. `except Exception` / `except BaseException` ({len(broad)}) ==")
    for p, ln, t in broad[:40]:
        print(f"  {p}:{ln}  except {t}")
    print()
    print(f"== F3. Swallowed exceptions (except: pass / ...) ({len(swallow)}) ==")
    for p, ln in swallow:
        print(f"  {p}:{ln}")
    print()


def audit_raise_generic():
    items = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                func = node.exc.func
                name = ast.unparse(func)
                if name in {"Exception", "BaseException", "RuntimeError"}:
                    items.append((p, node.lineno, name))
    print(f"== F4. Raise of generic Exception / RuntimeError ({len(items)}) ==")
    by = Counter(n for _, _, n in items)
    for k, v in by.most_common():
        print(f"  {v:3d}  {k}")
    print()


# -----------------------------------------------------------------------------
# G. MAINTAINABILITY & RISK
# -----------------------------------------------------------------------------

def audit_todos():
    rx = re.compile(r"\b(TODO|FIXME|XXX|HACK|TEMP)\b", re.IGNORECASE)
    items = []
    for p in walk(APP, SCRIPTS, TESTS):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                items.append((p, i, line.strip()[:100]))
    print(f"== G1. TODO/FIXME/XXX/HACK markers ({len(items)}) ==")
    counts: dict[str, int] = Counter()
    for _path, _, line in items:
        m = re.search(r"(TODO|FIXME|XXX|HACK|TEMP)", line, re.IGNORECASE)
        if m:
            counts[m.group(1).upper()] += 1
    for k, v in counts.most_common():
        print(f"  {k}: {v}")
    print("  -- first 30 occurrences:")
    for p, ln, line in items[:30]:
        print(f"  {p}:{ln}  {line}")
    print()


def audit_hardcoded_paths_urls():
    rx_url = re.compile(r"https?://[\w./?=&#%-]+")
    rx_path = re.compile(r"[A-Z]:[\\/](?:[\w.-]+[\\/]){2,}|/(?:home|var|etc|tmp)/[\w./-]+")
    rx_magic = re.compile(r"(?:timeout|TIMEOUT|sleep|retry|MAX_|SIZE)=?\s*\(?\s*([0-9]{3,})")
    urls, paths, magic = [], [], []
    for p in walk(APP):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx_url.search(line):
                urls.append((p, i, line.strip()[:120]))
            if rx_path.search(line):
                paths.append((p, i, line.strip()[:120]))
            m = rx_magic.search(line)
            if m and "test_" not in str(p).lower():
                magic.append((p, i, line.strip()[:120]))
    print(f"== G2. Hardcoded URLs ({len(urls)}) ==")
    for p, ln, line in urls[:20]:
        print(f"  {p}:{ln}  {line}")
    print()
    print(f"== G3. Hardcoded absolute paths ({len(paths)}) ==")
    for p, ln, line in paths[:20]:
        print(f"  {p}:{ln}  {line}")
    print()
    print(f"== G4. Magic-number-ish constants (3+ digits inline) ({len(magic)}) ==")
    for p, ln, line in magic[:30]:
        print(f"  {p}:{ln}  {line}")
    print()


def audit_credentials_risk():
    rx_secret = re.compile(r"(?i)(?:api[_-]?key|password|secret|token)\s*=\s*[\"']([^\"']{6,})[\"']")
    items = []
    for p in walk(APP, SCRIPTS):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = rx_secret.search(line)
            if m:
                value = m.group(1)
                if "replace-with" in value.lower() or "your-" in value.lower() or "<" in value:
                    continue
                items.append((p, i, line.strip()[:120]))
    print(f"== G5. Possible hard-coded credentials ({len(items)}) ==")
    for p, ln, line in items[:30]:
        print(f"  {p}:{ln}  {line}")
    print()


_DB_CALL_MARKERS = (
    "db.query",
    "db.scalar",
    "db.scalars",
    "db.execute",
    "session.query",
    "session.scalar",
    "session.execute",
)


def _is_bounded_range_retry(n: ast.For) -> bool:
    """``for _ in range(N): ...`` collision-retry idiom (bounded N)."""
    target_is_discard = isinstance(n.target, ast.Name) and n.target.id == "_"
    iter_is_range = (
        isinstance(n.iter, ast.Call)
        and isinstance(n.iter.func, ast.Name)
        and n.iter.func.id == "range"
    )
    return target_is_discard and iter_is_range


class _NPlusOneVisitor(ast.NodeVisitor):
    def __init__(self, file_path: pathlib.Path, items: list):
        self.loop_stack = 0
        self._file_path = file_path
        self._items = items

    def _visit_loop(self, iter_expr, body, orelse):
        # iter expression evaluates ONCE — stream consumer pattern.
        if iter_expr is not None:
            self.visit(iter_expr)
        self.loop_stack += 1
        for stmt in body:
            self.visit(stmt)
        self.loop_stack -= 1
        for stmt in orelse:
            self.visit(stmt)

    def visit_For(self, n):
        if _is_bounded_range_retry(n):
            return
        self._visit_loop(n.iter, n.body, n.orelse)

    def visit_AsyncFor(self, n):
        self._visit_loop(n.iter, n.body, n.orelse)

    def visit_While(self, n):
        # `while True:` is the project's collision-retry idiom.
        if isinstance(n.test, ast.Constant) and n.test.value is True:
            return
        self._visit_loop(None, n.body, n.orelse)
        self.visit(n.test)

    def visit_Call(self, n):
        if self.loop_stack > 0:
            src = ast.unparse(n.func)
            if any(m in src for m in _DB_CALL_MARKERS):
                self._items.append((self._file_path, n.lineno, src))
        self.generic_visit(n)


def audit_n_plus_one():
    """db.query / db.scalar / select(...) calls inside a for-loop body."""
    items = []
    for p in walk(APP):
        tree = parse(p)
        if not tree:
            continue
        _NPlusOneVisitor(p, items).visit(tree)
    print(f"== G6. DB call inside a loop (N+1 risk) ({len(items)}) ==")
    by_file = defaultdict(list)
    for p, ln, src in items:
        by_file[p].append((ln, src))
    for p, locs in sorted(by_file.items(), key=lambda x: -len(x[1]))[:20]:
        print(f"  {len(locs):3d}  {p}")
        for ln, src in locs[:3]:
            print(f"          L{ln} {src}")
    print()


def audit_test_coverage_by_module():
    """Map each app/ module to whether a test file references it directly."""
    grep_targets: dict[str, int] = {}
    for p in walk(APP):
        if p.name == "__init__.py":
            continue
        rel = str(p).replace(os.sep, "/").removesuffix(".py")
        mod = rel.replace("/", ".")
        grep_targets[mod] = 0

    body_blob: list[str] = []
    for p in walk(TESTS):
        with contextlib.suppress(Exception):
            body_blob.append(p.read_text(encoding="utf-8", errors="ignore"))
    blob = "\n".join(body_blob)
    for mod in grep_targets:
        if mod in blob:
            grep_targets[mod] = 1

    unreferenced = sorted(m for m, hit in grep_targets.items() if not hit)
    print(f"== G7. App modules never referenced by tests ({len(unreferenced)} of {len(grep_targets)}) ==")
    for m in unreferenced:
        print(f"  {m}")
    print()


# -----------------------------------------------------------------------------
# RUN
# -----------------------------------------------------------------------------

def main() -> None:
    print("=" * 78)
    print("CODEBASE AUDIT — read-only")
    print("=" * 78)
    audit_file_loc()
    audit_surface_area()
    audit_long_functions()
    audit_nesting_depth()
    audit_directory_density()
    audit_import_graph_and_cycles()
    audit_layer_violations()
    audit_sql_in_routes_or_services()
    audit_import_star()
    audit_naming_smells()
    audit_no_underscore_split()
    audit_globals_and_module_state()
    audit_lru_cache_singletons()
    audit_type_hint_coverage()
    audit_deep_arg_dicts()
    audit_return_type_inconsistency()
    audit_bare_except()
    audit_raise_generic()
    audit_todos()
    audit_hardcoded_paths_urls()
    audit_credentials_risk()
    audit_n_plus_one()
    audit_test_coverage_by_module()


if __name__ == "__main__":
    main()
