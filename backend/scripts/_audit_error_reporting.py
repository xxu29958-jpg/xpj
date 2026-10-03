"""Read-only, bounded error-reporting ownership guard. Exit 0/1/2 = pass/block/incomplete."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from adr_contract_git import select_ratchet_base
from error_reporting_contract import REQUIRED_FILES, REVIEWED_BOUNDARIES, common_contract
from error_reporting_rules import changed_boundaries
from repository_weight_sources import exact_commit, exclusion, git_bytes, read_snapshot, source_owner

ROOT = Path(__file__).resolve().parents[2]


def _sources(repo: Path, head: str, worktree: bool) -> dict[str, str]:
    files, _identities, _excluded = read_snapshot(repo, head)
    if worktree:
        paths = git_bytes(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
        for path in paths:
            if not path or exclusion(path) is not None:
                continue
            location = repo / path
            if location.is_file():
                files[path] = location.read_text(encoding="utf-8-sig")
            else:
                files.pop(path, None)
    return files


def _incremental(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    findings = []
    for path in sorted(set(before) | set(after)):
        if source_owner(path)[1] != "production" or before.get(path) == after.get(path):
            continue
        if not path.endswith((".py", ".kt")):
            findings.append({"status": "NOT_ANALYZED", "path": path, "rule": "language-scope",
                "observation": "Only Python AST and calibrated Kotlin lexical boundaries are analyzed."})
            continue
        changes = changed_boundaries(before.get(path, ""), after.get(path, ""), kotlin=path.endswith(".kt"))
        for item in changes:
            reviewed = REVIEWED_BOUNDARIES.get((path, item["symbol"]))
            accepted = reviewed is not None and reviewed["sha256"] == item["symbol_sha256"]
            findings.append({**item, "path": path, "status": "INHERITED" if accepted else "NEEDS_REVIEW",
                "observation": reviewed if accepted else "new/changed related boundary has no verified reporting owner"})
        if not changes:
            findings.append({"status": "INHERITED", "path": path, "rule": "no-new-boundary",
                "observation": "No new supported independent output/terminal boundary; ordinary entry inherits its existing owner."})
    return findings


def audit(args: argparse.Namespace) -> dict:
    env = dict(os.environ)
    if args.base:
        env["XPJ_AUDIT_BASE_REF"] = args.base
    selected, error = select_ratchet_base(args.repo, env)
    if selected is None:
        raise ValueError(error)
    head = exact_commit(args.repo, "HEAD", "qualification HEAD")
    source = exact_commit(args.repo, args.source or "HEAD", "source HEAD")
    git_bytes(args.repo, "merge-base", "--is-ancestor", source, head)
    before = _sources(args.repo, selected.commit, False)
    after = _sources(args.repo, head, args.worktree)
    findings = common_contract(after) + _incremental(before, after)
    return {"base": selected.commit, "qualification_sha": head, "source_sha": source,
        "evidence": "working-tree" if args.worktree else "committed-tree", "required_sources": list(REQUIRED_FILES),
        "coverage": "Python imported/aliased executors, broad terminal catches/suppress, logging configuration; "
            "Kotlin broad catches/Log.e,w lexical candidates and selected common Android wiring. "
            "No dynamic call-graph, arbitrary alias/dataflow or all-language safety proof.",
        "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--base")
    parser.add_argument("--source", default=os.environ.get("XPJ_WEIGHT_SOURCE_SHA"))
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args()
    try:
        report = audit(args)
    except (OSError, ValueError, SyntaxError, subprocess.CalledProcessError) as error:
        print(f"ERROR error-reporting input/parse incomplete: {error}")
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    blocked = any(item["status"] in {"VIOLATION", "NEEDS_REVIEW"} for item in report["findings"])
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
