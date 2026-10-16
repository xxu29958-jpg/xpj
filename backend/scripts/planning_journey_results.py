"""Bind the existing business result to the group and APK actually executed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_business(result: dict, identity: dict) -> None:
    for key in ("group", "checkout_sha", "source_sha", "apk_sha256"):
        if not identity.get(key) or result.get(key) != identity[key]:
            raise ValueError(f"Business result {key} does not match the actual execution")
    if not re.fullmatch(r"[a-f0-9]{64}", result["apk_sha256"]) or not result.get("verified_leg"):
        raise ValueError("Business result lacks APK identity or completed business assertions")


def record_execution(evidence: Path, identity: dict, outcome: str) -> dict:
    states = {"success": "passed", "failure": "failed", "cancelled": "cancelled", "skipped": "skipped"}
    if outcome not in states:
        raise ValueError(f"Unknown execution outcome: {outcome}")
    report = {**identity, "status": states[outcome], "executed": outcome != "skipped"}
    if outcome == "success":
        business = evidence / "business-result.json"
        try:
            validate_business(_read(business), identity)
            report["business_result_sha256"] = _hash(business)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report.update(status="failed", error=str(exc))
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "execution-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _latest_reports(evidence: Path, selection: dict) -> dict[str, tuple[Path, dict]]:
    latest: dict[str, tuple[Path, dict]] = {}
    for path in evidence.rglob("execution-result.json"):
        report = _read(path)
        for key in ("checkout_sha", "source_sha", "run_id"):
            if report.get(key) != selection[key]:
                raise ValueError(f"Execution {key} mismatch: {path.name}")
        group = report["group"]
        if group not in selection["selected"]:
            raise ValueError(f"Unrequested execution group: {group}")
        attempt = int(report["run_attempt"])
        if attempt < 1 or attempt > int(os.environ.get("GITHUB_RUN_ATTEMPT", selection["run_attempt"])):
            raise ValueError("Execution attempt is outside the current run")
        prior = latest.get(group)
        if prior and attempt == int(prior[1]["run_attempt"]):
            raise ValueError(f"Duplicate execution for {group} attempt {attempt}")
        if prior is None or attempt > int(prior[1]["run_attempt"]):
            latest[group] = path, report
    return latest


def verify_results(selection: dict, evidence: Path, execution_result: str) -> dict:
    selected = selection["selected"]
    if not selected:
        if execution_result != "skipped" or not selection.get("reason"):
            raise ValueError("Unselected journeys must be explicitly not applicable")
        return {**selection, "status": "not-applicable", "executed": []}
    latest = _latest_reports(evidence, selection)
    statuses = {group: latest[group][1]["status"] if group in latest else "missing" for group in selected}
    summary = {**selection, "status": "failed", "groups": statuses,
        "executed": [group for group, (_, report) in latest.items() if report["executed"]]}
    if execution_result != "success" or any(value != "passed" for value in statuses.values()):
        summary["error"] = f"Required consumer execution did not pass: {execution_result} / {statuses}"
        return summary
    apk_hashes: set[str] = set()
    for path, report in latest.values():
        business = path.with_name("business-result.json")
        validate_business(_read(business), report)
        if _hash(business) != report["business_result_sha256"]:
            raise ValueError("Business result changed after execution qualification")
        apk_hashes.add(report["apk_sha256"])
    if len(apk_hashes) != 1:
        raise ValueError("Different APKs cannot form a single consumer qualification")
    return {**summary, "status": "passed", "apk_sha256": apk_hashes.pop()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("record", "verify"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--apk", type=Path)
    args = parser.parse_args()
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if checkout != os.environ["GITHUB_SHA"]:
        raise ValueError("Unexpected qualification checkout")
    if args.command == "record":
        identity = {"group": os.environ["TICKETBOX_JOURNEY_GROUP"], "checkout_sha": checkout,
            "source_sha": os.environ["TICKETBOX_JOURNEY_SOURCE_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "apk_sha256": _hash(args.apk) if args.apk and args.apk.is_file() else None}
        report = record_execution(args.evidence, identity, os.environ["JOURNEY_OUTCOME"])
    else:
        selection = _read(args.selection)
        if selection["checkout_sha"] != checkout or selection["source_sha"] != os.environ["TICKETBOX_JOURNEY_SOURCE_SHA"]:
            raise ValueError("Selection belongs to another checkout or source")
        try:
            if selection["run_id"] != os.environ["GITHUB_RUN_ID"]:
                raise ValueError("Selection belongs to another run")
            report = verify_results(selection, args.evidence, os.environ["CONSUMERS_RESULT"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report = {**selection, "status": "failed", "error": str(exc)}
        args.evidence.mkdir(parents=True, exist_ok=True)
        (args.evidence / "qualification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in {"passed", "not-applicable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
