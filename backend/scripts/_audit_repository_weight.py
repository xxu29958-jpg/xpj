"""Whole-repository source weight and debt delta. Never executes measured code."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import yaml
from adr_contract_git import select_ratchet_base
from ci_gap_trigger_scope import classify_ci_decision
from engineering_task_map import render_task, resolve_task
from repository_weight_debt import android_policy_failures
from repository_weight_report import (
    compare_snapshots,
    measure_snapshot,
    query_report,
    render_query,
    render_report,
)
from repository_weight_sources import exact_commit, git_bytes, git_changed_paths, git_file_hunks, read_snapshot

ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_report(repo: Path, base: str, head: str) -> dict:
    base_sha, head_sha = exact_commit(repo, base, "base"), exact_commit(repo, head, "head")
    try:
        git_bytes(repo, "merge-base", "--is-ancestor", base_sha, head_sha)
    except subprocess.CalledProcessError as exc:
        raise ValueError("exact base is not an ancestor of the measured head") from exc
    started = time.monotonic()
    started_utc = _utc_now()
    base_files, base_excluded = read_snapshot(repo, base_sha)
    head_files, head_excluded = read_snapshot(repo, head_sha)
    before = measure_snapshot(base_sha, base_files, base_excluded)
    after = measure_snapshot(head_sha, head_files, head_excluded)
    report = compare_snapshots(before, after, android_policy_failures(base_files, head_files))
    git_changes = git_changed_paths(repo, base_sha, head_sha)
    report["git_changes"] = git_changes
    report["git_hunks"] = git_file_hunks(repo, base_sha, head_sha)
    report["classifier"] = classify_ci_decision(row["path"] for row in git_changes)
    report["classifier_identity"] = {
        "view": "audit_pair",
        "diff_base": base_sha,
        "diff_head": head_sha,
        "not": "CI event decision; CI scope uses event base/head and may full-run without a base",
    }
    report["timing"] = {
        "elapsed_s": round(time.monotonic() - started, 3),
        "started_utc": started_utc,
        "ended_utc": _utc_now(),
        "clock": "monotonic+utc",
    }
    return report


def _query_requested(args: argparse.Namespace) -> bool:
    return bool(args.path or args.module or args.symbol or args.changes or args.task)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--json", type=Path, default=os.environ.get("XPJ_CODEBASE_WEIGHT_JSON"))
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--from-json", type=Path, dest="from_json")
    parser.add_argument("--path")
    parser.add_argument("--module")
    parser.add_argument("--symbol")
    parser.add_argument("--changes", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        if args.task and not args.from_json and args.base is None:
            print(render_task(resolve_task(args.task, args.repo)), end="")
            return 0
        if args.from_json:
            report = json.loads(args.from_json.read_text(encoding="utf-8"))
            report["historical"] = True
            if not _query_requested(args):
                raise ValueError("query flags required with --from-json")
            if args.task:
                print(render_task(resolve_task(args.task, args.repo)), end="")
            result = query_report(
                report, path=args.path, module=args.module, symbol=args.symbol,
                changes=args.changes, limit=args.limit,
            )
            print(render_query(result), end="")
            return 2 if result["missing"]["git_changes"] and args.changes else 0
        base = args.base
        if not base:
            selected, error = select_ratchet_base(args.repo, dict(os.environ))
            if selected is None:
                raise ValueError(error or "cannot resolve exact base")
            base = selected.commit
        report = build_report(args.repo, base, args.head)
        rendered = render_report(report)
        print(rendered, end="")
        if _query_requested(args):
            if args.task:
                print(render_task(resolve_task(args.task, args.repo)), end="")
            print(render_query(query_report(
                report, path=args.path, module=args.module, symbol=args.symbol,
                changes=args.changes, limit=args.limit,
            )), end="")
        if args.json:
            args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.summary:
            with args.summary.open("a", encoding="utf-8") as output:
                fence = chr(96) * 3
                output.write("### Repository codebase weight\n\n" + fence + "text\n" + rendered + fence + "\n")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"CODEBASE WEIGHT INCOMPLETE: {exc}", file=sys.stderr)
        return 2
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
