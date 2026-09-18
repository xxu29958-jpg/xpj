"""Resolve the heavy CI jobs required by a pull request.

This is deliberately a path classifier, not a test-impact engine.  Unknown
paths and CI-policy changes fall back to the complete job set. Explanation is
rendered from the same decision that produced the five boolean outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from .ci_gap_trigger_scope import CI_HEAVY_SCOPES, classify_ci_decision
    from .postgres_release_policy import POSTGRES_RELEASE_POLICY
else:
    from ci_gap_trigger_scope import CI_HEAVY_SCOPES, classify_ci_decision
    from postgres_release_policy import POSTGRES_RELEASE_POLICY


def changed_paths(base: str, head: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"],
        check=True,
        capture_output=True,
    )
    return [
        entry.decode("utf-8", errors="surrogateescape")
        for entry in completed.stdout.split(b"\0")
        if entry
    ]


def write_outputs(path: Path, scopes: dict[str, bool]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for scope in CI_HEAVY_SCOPES:
            output.write(f"{scope}={'true' if scopes[scope] else 'false'}\n")
        output.write(f"postgres_matrix={POSTGRES_RELEASE_POLICY.matrix_json()}\n")


def resolve_ci_scope(event: str, base: str, head: str) -> dict[str, object]:
    identity = {
        "event": event,
        "diff_base": base or None,
        "diff_head": head or None,
        "source_kind": "event_diff",
    }
    if event not in {"pull_request", "push"} or not base or not head:
        decision = classify_ci_decision([])
        reason = "event has no trusted incremental diff base; running all heavy jobs"
        decision["reason"] = reason
        decision["status"] = "UNKNOWN_FULL"
        decision["identity"] = identity
        lanes = decision.get("lanes")
        if isinstance(lanes, dict):
            for lane in lanes.values():
                if isinstance(lane, dict):
                    lane["reason"] = reason
        return decision
    try:
        paths = changed_paths(base, head)
    except (OSError, subprocess.CalledProcessError) as exc:
        decision = classify_ci_decision([])
        reason = f"diff unavailable; running all heavy jobs: {exc}"
        decision["reason"] = reason
        decision["status"] = "UNKNOWN_FULL"
        decision["identity"] = identity
        decision["diff_error"] = type(exc).__name__
        lanes = decision.get("lanes")
        if isinstance(lanes, dict):
            for lane in lanes.values():
                if isinstance(lane, dict):
                    lane["reason"] = reason
        return decision
    decision = classify_ci_decision(paths)
    decision["identity"] = identity
    decision["git_paths"] = paths
    return decision


def render_scope_explanation(decision: dict[str, object]) -> str:
    identity = decision.get("identity") if isinstance(decision.get("identity"), dict) else {}
    scopes = decision["scopes"]
    assert isinstance(scopes, dict)
    lines = [
        "CI SCOPE",
        f"event={identity.get('event') or 'unknown'} base={identity.get('diff_base') or '(none)'} head={identity.get('diff_head') or '(none)'}",
        f"decision={decision['status']}: {decision['reason']}",
        f"resident: {decision.get('resident')}",
        "selected: " + ", ".join(f"{name}={'true' if scopes[name] else 'false'}" for name in CI_HEAVY_SCOPES),
    ]
    lanes = decision.get("lanes")
    if isinstance(lanes, dict):
        lines.append("lanes:")
        for name in CI_HEAVY_SCOPES:
            lane = lanes.get(name) or {}
            lines.append(f"  {name}: {lane.get('status')} ({lane.get('reason')})")
    ignored = decision.get("ignored_always_on") or []
    if ignored:
        lines.append("ignored always-on contract paths: " + json.dumps(ignored, ensure_ascii=False))
    hits = decision.get("hits") or []
    if isinstance(hits, list) and hits:
        lines.append("hits:")
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            consumer = f" consumer={hit['consumer']}" if hit.get("consumer") else ""
            lines.append(
                f"  {json.dumps(hit['path'], ensure_ascii=False)} {hit.get('kind')} {json.dumps(hit.get('entry'), ensure_ascii=False)}"
                f" -> {','.join(hit.get('scopes') or [])}{consumer}"
            )
    git_paths = decision.get("git_paths")
    if isinstance(git_paths, list):
        lines.append(f"git_paths={len(git_paths)}")
        for path in git_paths:
            lines.append(f"  {json.dumps(path, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _write_summary(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as output:
        fence = chr(96) * 3
        output.write("### CI scope\n\n" + fence + "text\n" + text + fence + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--explain-json", type=Path)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    decision = resolve_ci_scope(args.event, args.base, args.head)
    scopes = decision["scopes"]
    assert isinstance(scopes, dict)
    write_outputs(args.output, {name: bool(scopes[name]) for name in CI_HEAVY_SCOPES})
    try:
        rendered = render_scope_explanation(decision)
        print(rendered, end="")
        if args.explain_json:
            args.explain_json.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.summary:
            _write_summary(args.summary, rendered)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"CI SCOPE EXPLANATION ERROR: {exc}")
    print(
        "CI heavy-job scope: "
        + ", ".join(f"{key}={scopes[key]}" for key in CI_HEAVY_SCOPES)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
