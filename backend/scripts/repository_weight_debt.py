"""Debt sources retain their native meaning; no universal complexity score."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import yaml
from repository_weight_sources import DETEKT_BASELINES, DETEKT_POLICY

DETEKT_LIMITS = {
    "CyclomaticComplexMethod": ("allowedComplexity",),
    "LargeClass": ("allowedLines",),
    "LongMethod": ("allowedLines",),
    "LongParameterList": ("allowedFunctionParameters", "allowedConstructorParameters"),
    "NestedBlockDepth": ("allowedDepth",),
    "TooManyFunctions": (
        "allowedFunctionsPerFile", "allowedFunctionsPerClass", "allowedFunctionsPerInterface",
        "allowedFunctionsPerObject", "allowedFunctionsPerEnum",
    ),
}


def python_complexity(files: dict[str, str], records: list[dict]) -> tuple[dict[str, int], list[dict]]:
    python = {record["path"]: record for record in records if record["language"] == "Python"}
    counters: Counter[str] = Counter()
    findings: list[dict] = []
    for record in python.values():
        counters[f"python_c901:{record['module']}:{record['role']}"] += 0
        counters[f"python_c901_excess:{record['module']}:{record['role']}"] += 0
    if not python:
        return dict(counters), findings
    with tempfile.TemporaryDirectory(prefix="ticketbox-weight-ruff-") as directory:
        root = Path(directory)
        for index, path in enumerate(python):
            record_path = root / f"source_{index}.py"
            record_path.write_text(files[path], encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache", "--ignore-noqa",
                "--target-version", "py311", "--select", "C901", "--config",
                "lint.mccabe.max-complexity=15", "--output-format", "json", str(root),
            ],
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode not in {0, 1}:
            raise ValueError("native Ruff complexity scan did not complete")
        measured = json.loads(result.stdout)
        source_paths = list(python)
        for issue in measured:
            if issue["code"] != "C901":
                raise ValueError("native Ruff reported an unmeasurable source error")
            filename = Path(issue["filename"]).stem
            path = source_paths[int(filename.removeprefix("source_"))]
            record = python[path]
            match = re.search(r"\((\d+) > 15\)", issue["message"])
            if match is None:
                raise ValueError("native Ruff C901 format changed; cannot measure debt")
            key = f"{record['module']}:{record['role']}"
            counters[f"python_c901:{key}"] += 1
            counters[f"python_c901_excess:{key}"] += int(match[1]) - 15
            findings.append({"path": path, "line": issue["location"]["row"], "complexity": int(match[1])})
    return dict(counters), findings


def android_recorded_debt(files: dict[str, str]) -> dict[str, int]:
    counters: Counter[str] = Counter()
    for path, role in DETEKT_BASELINES.items():
        counters[f"android_detekt:{role}"] += 0
        if path not in files:
            continue
        root = ET.fromstring(files[path])
        if root.tag != "SmellBaseline" or root.find("CurrentIssues") is None:
            raise ValueError(f"invalid Detekt debt metadata: {path}")
        for issue in root.findall("./CurrentIssues/ID") + root.findall("./ManuallySuppressedIssues/ID"):
            if not issue.text or ":" not in issue.text:
                raise ValueError(f"invalid Detekt debt identity: {path}")
            counters[f"android_detekt:{role}"] += 1
            counters[f"android_detekt:{role}:{issue.text.split(':', 1)[0]}"] += 1
    return dict(counters)


def android_policy_failures(base: dict[str, str], current: dict[str, str]) -> list[str]:
    failures: list[str] = []
    for path in DETEKT_BASELINES:
        if path in base and path not in current:
            failures.append(f"removed recorded debt authority: {path}")
    if DETEKT_POLICY not in base:
        return failures
    if DETEKT_POLICY not in current:
        return [*failures, "removed Android complexity policy"]
    old = yaml.safe_load(base[DETEKT_POLICY])["complexity"]
    new = yaml.safe_load(current[DETEKT_POLICY])["complexity"]
    if new.get("active") is not True:
        failures.append("disabled Android complexity rules")
    for rule, limits in DETEKT_LIMITS.items():
        previous, candidate = old[rule], new.get(rule, {})
        if candidate.get("active") is not True:
            failures.append(f"disabled Android complexity rule: {rule}")
        for limit in limits:
            if limit not in candidate or candidate[limit] > previous[limit]:
                failures.append(f"relaxed Android complexity threshold: {rule}.{limit}")
        comparable = set(previous) | set(candidate)
        if any(previous.get(key) != candidate.get(key) for key in comparable - set(limits) - {"active"}):
            failures.append(f"changed Android complexity exemptions: {rule}")
    return failures


def new_suppressions(base: list[dict], current: list[dict]) -> list[dict]:
    # Moving an identical existing directive is not new debt. Replacing its rule is.
    remaining = Counter(row["signature"] for row in base)
    added: list[dict] = []
    for row in current:
        if remaining[row["signature"]] > 0:
            remaining[row["signature"]] -= 1
        else:
            added.append(row)
    return added
