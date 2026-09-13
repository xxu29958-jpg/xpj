"""One report model feeds the CLI, CI summary and drill-down JSON."""

from __future__ import annotations

from collections import defaultdict
from importlib.metadata import version

from repository_weight_debt import android_recorded_debt, new_suppressions, python_complexity
from repository_weight_functions import measure_functions
from repository_weight_sources import exclusion, measure_source

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
    return {
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
        f"CODEBASE WEIGHT — exact {current['sha']}", f"Base: {base['sha']}",
        "LOC = physical source lines (code + comment-only + blank); no LOC ceiling.", "",
    ]
    labels = {
        "production_loc": "Production LOC", "test_loc": "Test LOC", "executable_total": "Executable total (P+T)",
        "tooling_loc": "Engineering tooling", "source_total": "All source total",
    }
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
    changed_modules = sorted({module for row in report["changes"] for module in row["modules"]})
    lines.append(f"\nChanged source files: {len(report['changes'])}; modules: {', '.join(changed_modules) or 'none'}")
    lines.append("Tools: " + ", ".join(f"{key}={value}" for key, value in report["tools"].items()))
    lines.append(f"PowerShell parser: {current['powershell_parser'] or 'no PowerShell source'}")
    lines.extend(f"Coverage: {report['policy'][key]}" for key in ("android_complexity", "function_metrics", "non_function_source", "verdict_scope"))
    if report["advisories"]:
        lines.append("\nSize changes requiring review (not automatic complexity debt):")
        lines.extend(f"  {advisory}" for advisory in report["advisories"])
    if report["failures"]:
        lines.append("\nFailures:")
        lines.extend(f"  {failure}" for failure in report["failures"])
    lines.append(f"\nVerdict: {report['verdict']}")
    return "\n".join(lines) + "\n"
