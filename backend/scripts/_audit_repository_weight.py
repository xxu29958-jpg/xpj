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


def _commit_parents(repo: Path, sha: str) -> set[str]:
    text = git_bytes(repo, "rev-parse", f"{sha}^@").decode("ascii")
    return {line.strip() for line in text.splitlines() if line.strip()}


def _assert_source_related(repo: Path, source_sha: str, measurement_sha: str) -> None:
    if source_sha == measurement_sha:
        return
    try:
        git_bytes(repo, "merge-base", "--is-ancestor", source_sha, measurement_sha)
        return
    except subprocess.CalledProcessError:
        pass
    if source_sha in _commit_parents(repo, measurement_sha):
        return
    raise ValueError("source_sha is not an ancestor or parent of measurement_sha")


def _measurement_kind(event: str | None, source_sha: str, measurement_sha: str) -> str:
    if source_sha == measurement_sha:
        return "direct_head"
    if event == "pull_request":
        return "pull_request_merge"
    return "qualified_checkout"


def bind_report_identity(
    repo: Path,
    report: dict,
    *,
    base_sha: str,
    measurement_sha: str,
    source_sha: str,
    event: str | None,
) -> None:
    if report["current"]["sha"] != measurement_sha:
        raise ValueError("measurement_sha must equal current.sha")
    if report["base"]["sha"] != base_sha:
        raise ValueError("base_sha must equal base.sha")
    if event == "pull_request" and source_sha == measurement_sha:
        raise ValueError("pull_request report must not name the merge snapshot as source_sha")
    _assert_source_related(repo, source_sha, measurement_sha)
    report["identity"] = {
        "base_sha": base_sha,
        "measurement_sha": measurement_sha,
        "source_sha": source_sha,
        "measurement_kind": _measurement_kind(event, source_sha, measurement_sha),
        "event": event,
    }


def build_report(
    repo: Path,
    base: str,
    head: str,
    *,
    source_sha: str | None = None,
    event: str | None = None,
) -> dict:
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
    bind_report_identity(
        repo,
        report,
        base_sha=base_sha,
        measurement_sha=head_sha,
        source_sha=exact_commit(repo, source_sha or head_sha, "source"),
        event=event,
    )
    report["timing"] = {
        "elapsed_s": round(time.monotonic() - started, 3),
        "started_utc": started_utc,
        "ended_utc": _utc_now(),
        "clock": "monotonic+utc",
    }
    return report


def _query_requested(args: argparse.Namespace) -> bool:
    return bool(args.path or args.module or args.symbol or args.changes or args.task)


def _print_task(
    repo: Path,
    name: str,
    snapshot_sha: str,
    *,
    historical: bool,
    source_sha: str | None = None,
) -> None:
    print(
        render_task(
            resolve_task(
                name, repo, snapshot_sha, historical=historical, source_sha=source_sha,
            )
        ),
        end="",
    )


def _artifact_identity(report: dict) -> tuple[str, str]:
    identity = report.get("identity") if isinstance(report.get("identity"), dict) else {}
    measurement = identity.get("measurement_sha")
    source = identity.get("source_sha")
    if not measurement:
        raise ValueError("historical query requires identity.measurement_sha")
    if not source:
        raise ValueError("historical query requires identity.source_sha")
    return str(source), str(measurement)


def _query_from_args(report: dict, args: argparse.Namespace) -> dict:
    return query_report(
        report, path=args.path, module=args.module, symbol=args.symbol,
        changes=args.changes, limit=args.limit,
    )


def _run_from_json(args: argparse.Namespace) -> int:
    report = json.loads(args.from_json.read_text(encoding="utf-8"))
    report["historical"] = True
    if not _query_requested(args):
        raise ValueError("query flags required with --from-json")
    source_sha, measurement_sha = _artifact_identity(report)
    if args.task:
        _print_task(
            args.repo, args.task, measurement_sha, historical=True, source_sha=source_sha,
        )
    result = _query_from_args(report, args)
    print(render_query(result), end="")
    return 2 if result["missing"]["git_changes"] and args.changes else 0


def _write_live_outputs(report: dict, rendered: str, args: argparse.Namespace) -> None:
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as output:
            fence = chr(96) * 3
            output.write("### Repository codebase weight\n\n" + fence + "text\n" + rendered + fence + "\n")


def _run_live(args: argparse.Namespace) -> int:
    base = args.base
    if not base:
        selected, error = select_ratchet_base(args.repo, dict(os.environ))
        if selected is None:
            raise ValueError(error or "cannot resolve exact base")
        base = selected.commit
    report = build_report(
        args.repo,
        base,
        args.head,
        source_sha=args.source_sha,
        event=args.event,
    )
    rendered = render_report(report)
    print(rendered, end="")
    if _query_requested(args):
        if args.task:
            identity = report["identity"]
            _print_task(
                args.repo,
                args.task,
                str(identity["measurement_sha"]),
                historical=False,
                source_sha=str(identity["source_sha"]),
            )
        print(render_query(_query_from_args(report, args)), end="")
    _write_live_outputs(report, rendered, args)
    return 1 if report["failures"] else 0


def _parse_args() -> argparse.Namespace:
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
    parser.add_argument("--source-sha", default=os.environ.get("XPJ_WEIGHT_SOURCE_SHA"))
    parser.add_argument("--event", default=os.environ.get("XPJ_WEIGHT_EVENT"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        if args.task and not args.from_json and args.base is None:
            snapshot = exact_commit(args.repo, args.head, "head")
            source = exact_commit(args.repo, args.source_sha or snapshot, "source")
            _print_task(args.repo, args.task, snapshot, historical=False, source_sha=source)
            return 0
        if args.from_json:
            return _run_from_json(args)
        return _run_live(args)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"CODEBASE WEIGHT INCOMPLETE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
