"""Whole-repository source weight and debt delta. Never executes measured code."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from adr_contract_git import select_ratchet_base
from repository_weight_debt import android_policy_failures
from repository_weight_report import compare_snapshots, measure_snapshot, render_report
from repository_weight_sources import exact_commit, git_bytes, read_snapshot

ROOT = Path(__file__).resolve().parents[2]


def build_report(repo: Path, base: str, head: str) -> dict:
    base_sha, head_sha = exact_commit(repo, base, "base"), exact_commit(repo, head, "head")
    try:
        git_bytes(repo, "merge-base", "--is-ancestor", base_sha, head_sha)
    except subprocess.CalledProcessError as exc:
        raise ValueError("exact base is not an ancestor of the measured head") from exc
    base_files, base_excluded = read_snapshot(repo, base_sha)
    head_files, head_excluded = read_snapshot(repo, head_sha)
    before = measure_snapshot(base_sha, base_files, base_excluded)
    after = measure_snapshot(head_sha, head_files, head_excluded)
    return compare_snapshots(before, after, android_policy_failures(base_files, head_files))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--json", type=Path, default=os.environ.get("XPJ_CODEBASE_WEIGHT_JSON"))
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        base = args.base
        if not base:
            selected, error = select_ratchet_base(args.repo, dict(os.environ))
            if selected is None:
                raise ValueError(error or "cannot resolve exact base")
            base = selected.commit
        report = build_report(args.repo, base, args.head)
        rendered = render_report(report)
        print(rendered, end="")
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
