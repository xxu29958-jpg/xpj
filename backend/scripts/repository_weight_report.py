"""One report model feeds the CLI, CI summary and drill-down JSON."""

from __future__ import annotations

from collections import defaultdict
from importlib.metadata import version

from repository_weight_debt import android_recorded_debt, new_suppressions, python_complexity
from repository_weight_functions import measure_functions
from repository_weight_sources import DETEKT_BASELINES, exclusion, measure_source

ROLES = ("production", "test", "tooling")


def grouped_loc(records: list[dict], field: str) -> dict[str, dict[str, int]]:
    groups = defaultdict(lambda: {**dict.fromkeys(ROLES, 0), "files": 0})
    for record in records:
        groups[record[field]][record["role"]] += record["loc"]
        groups[record[field]]["files"] += 1
    return dict(sorted(groups.items()))


def measure_snapshot(sha: str, files: dict[str, str], excluded: dict[str, int]) -> dict:
    records: list[dict] = []
    suppressions: list[dict] = []
    for path, text in sorted(files.items()):
        if exclusion(path) is not None:
            continue
        record, directives = measure_source(path, text)
        records.append(record)
        suppressions.extend(directives)
    totals = {f"{role}_loc": sum(row["loc"] for row in records if row["role"] == role) for role in ROLES}
    totals["executable_total"] = totals["production_loc"] + totals["test_loc"]
    totals["source_total"] = totals["executable_total"] + totals["tooling_loc"]
    debt = {f"files_over_{limit}": sum(row["loc"] > limit for row in records) for limit in (500, 800, 1000)}
    python_debt, findings = python_complexity(files, records)
    debt.update(python_debt)
    debt.update(android_recorded_debt(files))
    functions, function_debt, powershell_version = measure_functions(files, records)
    debt.update(function_debt)
    return {
        "sha": sha, "totals": totals, "modules": grouped_loc(records, "module"),
        "languages": grouped_loc(records, "language"), "directories": grouped_loc(records, "directory"),
        "lines": {kind: sum(row[kind] for row in records) for kind in ("loc", "code", "comment", "blank")},
        "files": records, "excluded": excluded, "debt": dict(sorted(debt.items())),
        "python_complexity_findings": findings, "suppressions": suppressions,
        "functions": functions, "powershell_parser": powershell_version,
    }


def compare_snapshots(base: dict, current: dict, policy_failures: list[str]) -> dict:
    failures = list(policy_failures)
    advisories: list[str] = []
    for key in sorted(set(base["debt"]) | set(current["debt"])):
        before, after = base["debt"].get(key, 0), current["debt"].get(key, 0)
        if after > before:
            # Physical span includes SQL, fixtures, assertions and comments. It
            # locates review work; it cannot decide where an owner must be split.
            target = advisories if key.startswith(("files_over_", "long_functions:")) else failures
            target.append(f"{key}: {before} -> {after}")
    added = new_suppressions(base["suppressions"], current["suppressions"])
    if added:
        failures.append(f"new suppression signatures: {len(added)}")
    delta = {key: value - base["totals"][key] for key, value in current["totals"].items()}
    verdict = "DEBT REGRESSION" if failures else "NO DEBT REGRESSION"
    if not failures and not advisories and delta["production_loc"] > 0:
        verdict = "HEALTHY GROWTH"
    report = {
        "format_version": 1,
        "tools": {tool: version(tool) for tool in ("ruff", "Pygments", "PyYAML", "lizard")},
        "policy": {
            "loc": "Physical source lines, including comments and blanks; mixed lines count as code.",
            "ownership": "Each file has one module/role/primary language; migrations count once in production.",
            "python_complexity": "Pinned Ruff C901, threshold 15, isolated and ignore-noqa; count and excess.",
            "android_complexity": "Recorded Detekt baseline IDs, not live unsuppressed findings; native CI remains required.",
            "function_metrics": "Lizard CCN estimate (Python/Kotlin/Java/JS/TS/inline JS); PowerShell AST decisions; Inno lexical decision tokens, not CFG cyclomatic complexity. Complexity threshold 15; physical function length >80 is a review signal.",
            "non_function_source": "CSS/XML/declarative config have no function cyclomatic metric; source size remains included. Template rendering, dynamic code and Inno preprocessing/nested routine semantics are not evaluated.",
            "verdict_scope": "Measured complexity/known-debt/suppression gates only. File size and physical span growth require responsibility review, not mechanical splitting. Not architecture or product acceptance.",
        },
        "base": base, "current": current, "delta": delta, "new_suppressions": len(added),
        "added_suppression_records": added, "failures": failures, "advisories": advisories, "verdict": verdict,
        "changes": changed_sources(base["files"], current["files"]),
    }
    report["failure_details"] = failure_details(report)
    return report


def _file_role(snapshot: dict, path: str) -> tuple[str | None, str | None]:
    for row in snapshot.get("files", []):
        if row["path"] == path:
            return row.get("module"), row.get("role")
    return None, None


def _overlap(start: int, end: int, hunk_start: int, hunk_count: int) -> bool:
    if hunk_count <= 0:
        return start <= hunk_start + 1 <= end
    return start <= hunk_start + hunk_count - 1 and end >= hunk_start


def _debt_locations(report: dict, key: str) -> list[dict]:
    current = report["current"]
    if key.startswith("python_c901"):
        _prefix, module, role = key.split(":", 2)
        found: list[dict] = []
        for finding in current.get("python_complexity_findings", []):
            file_module, file_role = _file_role(current, finding["path"])
            if file_module == module and file_role == role:
                found.append({
                    "path": finding["path"], "line": finding["line"], "side": "head",
                    "value": finding["complexity"], "attribution": "unique",
                })
        return found
    if key.startswith("function_complexity"):
        _kind, language, module, role = key.split(":", 3)
        found = []
        for function in current.get("functions", []):
            if (
                function["language"] == language
                and function["module"] == module
                and function["role"] == role
                and function["complexity"] > 15
            ):
                found.append({
                    "path": function["path"], "line": function["line"], "end_line": function.get("end_line"),
                    "function": function["name"], "side": "head", "value": function["complexity"],
                    "attribution": "unique",
                })
        return found
    if key.startswith("android_detekt:"):
        role = key.split(":", 1)[1]
        path = next((candidate for candidate, mapped in DETEKT_BASELINES.items() if mapped == role), None)
        if path:
            return [{"path": path, "side": "head", "attribution": "unique"}]
    return []


def failure_details(report: dict) -> list[dict]:
    details: list[dict] = []
    for failure in report["failures"]:
        if failure.startswith("new suppression signatures"):
            records = report.get("added_suppression_records") or []
            if not records:
                details.append({
                    "failure": failure, "rule": "new_suppression", "side": "head",
                    "attribution": "cannot uniquely attribute",
                })
                continue
            for row in records:
                details.append({
                    "failure": failure, "rule": "new_suppression", "path": row.get("path"),
                    "line": row.get("line"), "signature": row.get("signature"), "side": "head",
                    "attribution": "unique",
                })
            continue
        if ": " in failure and " -> " in failure:
            key, delta = failure.split(": ", 1)
            before, after = (part.strip() for part in delta.split(" -> ", 1))
            locations = _debt_locations(report, key)
            item = {"failure": failure, "rule": key, "base": before, "head": after, "side": "head"}
            if locations:
                for location in locations:
                    details.append({**item, **location})
            else:
                details.append({**item, "attribution": "cannot uniquely attribute"})
            continue
        path = "android/detekt.yml" if "Android complexity" in failure else None
        details.append({
            "failure": failure, "rule": failure, "path": path, "side": "head",
            "attribution": "unique" if path else "cannot uniquely attribute",
        })
    return details


def changed_sources(base: list[dict], current: list[dict]) -> list[dict]:
    before, after = ({row["path"]: row for row in rows} for rows in (base, current))
    changes: list[dict] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path, {}), after.get(path, {})
        if old.get("normalized_source_sha256") != new.get("normalized_source_sha256"):
            changes.append({
                "path": path, "change": "modified" if old and new else "added" if new else "removed",
                "modules": sorted({row["module"] for row in (old, new) if row}),
                "loc_delta": new.get("loc", 0) - old.get("loc", 0),
            })
    return changes


def _function_touch(function: dict, hunks: list[dict], side: str) -> str:
    start, end = function["line"], function.get("end_line") or function["line"]
    unified = [row for row in hunks if row.get("kind") == "unified"]
    if any(row.get("kind") == "binary" for row in hunks) and not unified:
        return "file_changed"
    key_start = "new_start" if side == "head" else "old_start"
    key_count = "new_count" if side == "head" else "old_count"
    if any(_overlap(start, end, int(row[key_start]), int(row[key_count])) for row in unified):
        return "diff_intersects"
    if unified:
        return "file_changed"
    return "unmatched"


def _path_match(row_path: str, path: str | None) -> bool:
    return path is None or row_path == path or row_path.startswith(path)


def _deleted_functions(report: dict, path: str | None, module: str | None) -> list[dict]:
    current_keys = {(row["path"], row["name"], row["line"]) for row in report["current"]["functions"]}
    deleted: list[dict] = []
    for row in report["base"]["functions"]:
        key = (row["path"], row["name"], row["line"])
        if key in current_keys or not _path_match(row["path"], path):
            continue
        if module is None or row["module"] == module:
            deleted.append({**row, "touch": "deleted"})
    return deleted


def _function_touch_for_report(function: dict, report: dict, git_changes: list, measured: list) -> str:
    hunks = (report.get("git_hunks") or {}).get(function["path"])
    if hunks is None:
        if any(row["path"] == function["path"] for row in git_changes):
            return "unmatched"
        if any(row["path"] == function["path"] for row in measured):
            return "file_changed"
        return "inventory"
    return _function_touch(function, hunks, "head")


def query_report(
    report: dict,
    *,
    path: str | None = None,
    module: str | None = None,
    symbol: str | None = None,
    changes: bool = False,
    limit: int = 50,
) -> dict:
    git_changes = [row for row in report.get("git_changes") or [] if _path_match(row["path"], path)]
    measured = [row for row in report["changes"] if _path_match(row["path"], path)]
    files = list(report["current"]["files"])
    functions = list(report["current"]["functions"])
    if path:
        files = [row for row in files if _path_match(row["path"], path)]
        functions = [row for row in functions if _path_match(row["path"], path)]
    if module:
        files = [row for row in files if row["module"] == module]
        functions = [row for row in functions if row["module"] == module]
        measured = [row for row in measured if module in row.get("modules", [])]
    deleted = _deleted_functions(report, path, module) if changes or symbol else []
    matched_functions = []
    for function in functions:
        if symbol and symbol not in {function["name"], function["path"]}:
            continue
        matched_functions.append({**function, "touch": _function_touch_for_report(function, report, git_changes, measured)})
    if symbol:
        files = [row for row in files if any(item["path"] == row["path"] for item in matched_functions)]
    truncated = False

    def _clip(rows: list) -> list:
        nonlocal truncated
        if len(rows) > limit:
            truncated = True
            return rows[:limit]
        return rows

    show_changes = changes or bool(path or module)
    return {
        "verdict": report["verdict"],
        "verdict_scope": "unfiltered global verdict; query rows are a view",
        "identity": {
            "base": report["base"]["sha"],
            "head": report["current"]["sha"],
            "historical": bool(report.get("historical")),
        },
        "git_changes": _clip(git_changes if show_changes else []),
        "measured_changes": _clip(measured if show_changes else []),
        "files": _clip(files if path or module or symbol else []),
        "functions": _clip(matched_functions if symbol or path or module else []),
        "deleted_functions": _clip(deleted if symbol or changes else []),
        "failures": report.get("failure_details") or [],
        "truncated": truncated,
        "limit": limit,
        "missing": {
            "git_hunks": "git_hunks" not in report,
            "git_changes": "git_changes" not in report,
        },
    }
    return {
        "verdict": report["verdict"],
        "verdict_scope": "unfiltered global verdict; query rows are a view",
        "identity": {
            "base": report["base"]["sha"],
            "head": report["current"]["sha"],
            "historical": bool(report.get("historical")),
        },
        "git_changes": _clip(git_changes if show_changes else []),
        "measured_changes": _clip(measured if show_changes else []),
        "files": _clip(files if path or module or symbol else []),
        "functions": _clip(matched_functions if symbol or path or module else []),
        "deleted_functions": _clip(deleted if symbol or changes else []),
        "failures": report.get("failure_details") or [],
        "truncated": truncated,
        "limit": limit,
        "missing": {
            "git_hunks": "git_hunks" not in report,
            "git_changes": "git_changes" not in report,
        },
    }


def render_query(result: dict) -> str:
    lines = [
        f"GLOBAL VERDICT (unfiltered): {result['verdict']}",
        f"Query identity base={result['identity']['base']} head={result['identity']['head']}",
        f"truncated={str(result['truncated']).lower()} limit={result['limit']}",
    ]
    if result["missing"]["git_changes"] or result["missing"]["git_hunks"]:
        lines.append("missing: " + ", ".join(name for name, absent in result["missing"].items() if absent))
    for label, key in (
        ("Git changes (complete diff)", "git_changes"),
        ("Measured source changes", "measured_changes"),
        ("Files", "files"),
        ("Functions", "functions"),
        ("Deleted functions", "deleted_functions"),
    ):
        rows = result.get(key) or []
        lines.append(f"{label}: {len(rows)}")
        for row in rows:
            if "status" in row and "inventory" in row:
                lines.append(f"  {row['status']} {row['inventory']} {row['path']}")
            elif "change" in row:
                lines.append(f"  {row['change']} {row['path']} loc_delta={row.get('loc_delta')}")
            elif "touch" in row and "name" in row:
                lines.append(
                    f"  {row['touch']} {row['path']}:{row['line']} {row['name']}"
                )
            else:
                lines.append(f"  {row.get('module')}/{row.get('role')} {row.get('path')}")
    if result["truncated"]:
        lines.append(f"results truncated at {result['limit']}; raise --limit to expand")
    return "\n".join(lines) + "\n"


def _delta(value: int) -> str:
    return f"{value:+,}" if value else "0"


def _group_table(report: dict, field: str) -> list[str]:
    old, new = report["base"][field], report["current"][field]
    lines = [f"\n{field.title()} — files / production / test / tooling / LOC delta"]
    for name in sorted(set(old) | set(new)):
        before = old.get(name, dict.fromkeys(ROLES, 0))
        after = new.get(name, dict.fromkeys(ROLES, 0))
        values = " / ".join(f"{after[role]:,}" for role in ROLES)
        delta = sum(after[role] - before[role] for role in ROLES)
        lines.append(f"  {name:<25} {after.get('files', 0):,} / {values} / {_delta(delta)}")
    return lines


def _hotspots(current: dict) -> list[str]:
    lines = ["\nLargest source files (top 15)"]
    for row in sorted(current["files"], key=lambda row: (-row["loc"], row["path"]))[:15]:
        lines.append(f"  {row['loc']:>6,} LOC  {row['module']}/{row['role']}  {row['path']}")
    lines.append("\nComplex function hotspots (top 15 per metric; names are not cross-language scores)")
    functions = current["functions"]
    for metric in sorted({row["metric"] for row in functions}):
        rows = sorted((row for row in functions if row["metric"] == metric), key=lambda row: (-row["complexity"], row["path"], row["line"]))
        lines.append(f"  {metric} — {len(rows):,} measured units")
        for row in rows[:15]:
            lines.append(f"    {row['complexity']:>4}  {row['length']:>4}L  {row['path']}:{row['line']} {row['name']}")
    lines.append("\nLongest functions (top 10, physical span; script top-level excluded)")
    rows = sorted((row for row in functions if row["name"] != "<script>"), key=lambda row: (-row["length"], row["path"], row["line"]))
    lines.extend(f"  {row['length']:>5}L  {row['path']}:{row['line']} {row['name']}" for row in rows[:10])
    return lines


def render_report(report: dict) -> str:
    current, base = report["current"], report["base"]
    lines = [
        f"CODEBASE WEIGHT — exact {current['sha']}",
        f"Base: {base['sha']}",
        "Identity: audit pair of exact Git commits; dirty/untracked files are not measured.",
        "LOC = physical source lines (code + comment-only + blank); no LOC ceiling.",
        f"Verdict: {report['verdict']}",
        "",
    ]
    if report.get("failure_details"):
        lines.append("Failures:")
        for detail in report["failure_details"]:
            location = detail.get("path") or "no unique file"
            line = f":{detail['line']}" if detail.get("line") else ""
            function = f" {detail['function']}" if detail.get("function") else ""
            signature = f" signature={detail['signature']}" if detail.get("signature") else ""
            attribution = detail.get("attribution") or "cannot uniquely attribute"
            delta = ""
            if "base" in detail and "head" in detail:
                delta = f" {detail['base']} -> {detail['head']}"
            lines.append(
                f"  {detail.get('rule') or detail['failure']}{delta} {attribution} "
                f"{detail.get('side', 'head')} {location}{line}{function}{signature}"
            )
        lines.append("")
    git_changes = report.get("git_changes") or []
    lines.append(
        f"Changes: git_paths={len(git_changes)} measured_source={len(report['changes'])}"
    )
    unmeasured = [row["path"] for row in git_changes if row.get("inventory") == "unmeasured"]
    if unmeasured:
        lines.append(f"Unmeasured Git paths still classified by CI (not LOC): {len(unmeasured)}")
        lines.extend(f"  {path}" for path in unmeasured[:20])
    classifier = report.get("classifier")
    if isinstance(classifier, dict):
        identity = report.get("classifier_identity") or {}
        lines.append(
            f"Classifier view ({identity.get('view', 'audit_pair')}; not the CI event decision): "
            f"{classifier.get('status')} {classifier.get('reason')}"
        )
        scopes = classifier.get("scopes") or {}
        lines.append("  " + ", ".join(f"{name}={scopes.get(name)}" for name in scopes))
    changed_modules = sorted({module for row in report["changes"] for module in row["modules"]})
    lines.append(f"Changed source files: {len(report['changes'])}; modules: {', '.join(changed_modules) or 'none'}")
    lines.append("Tools: " + ", ".join(f"{key}={value}" for key, value in report["tools"].items()))
    lines.append(f"PowerShell parser: {current['powershell_parser'] or 'no PowerShell source'}")
    lines.extend(f"Coverage: {report['policy'][key]}" for key in ("android_complexity", "function_metrics", "non_function_source", "verdict_scope"))
    labels = {
        "production_loc": "Production LOC", "test_loc": "Test LOC", "executable_total": "Executable total (P+T)",
        "tooling_loc": "Engineering tooling", "source_total": "All source total",
    }
    lines.append("")
    for key, label in labels.items():
        lines.append(f"{label:<26} {current['totals'][key]:>10,}  {_delta(report['delta'][key]):>9}")
    lines.extend(_group_table(report, "modules"))
    lines.extend(_group_table(report, "languages"))
    lines.append("\nMeasured counts — current / delta (physical size is advisory)")
    for key in sorted(set(base["debt"]) | set(current["debt"])):
        value = current["debt"].get(key, 0)
        lines.append(f"  {key:<52} {value:>6,}  {_delta(value - base['debt'].get(key, 0)):>7}")
    lines.append(f"New suppressions: {report['new_suppressions']}")
    lines.append("\nLine composition (all source): " + ", ".join(f"{key}={value:,}" for key, value in current["lines"].items()))
    lines.extend(_hotspots(current))
    if report["advisories"]:
        lines.append("\nSize changes requiring review (not automatic complexity debt):")
        lines.extend(f"  {advisory}" for advisory in report["advisories"])
    if report["failures"] and not report.get("failure_details"):
        lines.append("\nFailures:")
        lines.extend(f"  {failure}" for failure in report["failures"])
    lines.append(f"\nVerdict: {report['verdict']}")
    return "\n".join(lines) + "\n"
