"""Fail-closed state machine for the PostgreSQL responsibility aggregator."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass

_LANES = ("ORDINARY", "REAL_DB", "RECOVERY")


@dataclass(frozen=True)
class Verification:
    ok: bool
    message: str


def verify(values: Mapping[str, str]) -> Verification:
    required = {
        "SCOPE_RESULT",
        "POSTGRES_SCOPE",
        "EXPECTED_SHA",
        "EXPECTED_SOURCE_SHA",
        "AGGREGATOR_SHA",
        "AGGREGATOR_SOURCE_SHA",
        "SCOPE_SHA",
        "SCOPE_SOURCE_SHA",
        *(f"{lane}_RESULT" for lane in _LANES),
    }
    lane_sha_keys = {f"{lane}_SHA" for lane in _LANES}
    lane_source_sha_keys = {f"{lane}_SOURCE_SHA" for lane in _LANES}
    missing = sorted(
        {key for key in required if not values.get(key)}
        | {key for key in lane_sha_keys | lane_source_sha_keys if key not in values}
    )
    if missing:
        return Verification(False, f"missing PostgreSQL CI result fields: {', '.join(missing)}")
    if values["SCOPE_RESULT"] != "success":
        return Verification(False, f"CI scope resolution did not succeed: {values['SCOPE_RESULT']}")
    expected_sha = values["EXPECTED_SHA"]
    for key in ("AGGREGATOR_SHA", "SCOPE_SHA"):
        if values[key] != expected_sha:
            return Verification(False, f"qualification SHA mismatch: {key}={values[key]}")
    expected_source_sha = values["EXPECTED_SOURCE_SHA"]
    for key in ("AGGREGATOR_SOURCE_SHA", "SCOPE_SOURCE_SHA"):
        if values[key] != expected_source_sha:
            return Verification(
                False,
                f"qualification source SHA mismatch: {key}={values[key]}",
            )

    scope = values["POSTGRES_SCOPE"]
    if scope == "false":
        wrong = [lane for lane in _LANES if values[f"{lane}_RESULT"] != "skipped"]
        if wrong:
            return Verification(False, f"PostgreSQL lanes ran outside scope: {', '.join(wrong)}")
        unexpected_sha = [lane for lane in _LANES if values.get(f"{lane}_SHA")]
        unexpected_source_sha = [
            lane for lane in _LANES if values.get(f"{lane}_SOURCE_SHA")
        ]
        if unexpected_sha or unexpected_source_sha:
            return Verification(
                False,
                "skipped PostgreSQL lanes reported a SHA: "
                f"{', '.join(sorted(set(unexpected_sha + unexpected_source_sha)))}",
            )
        return Verification(True, "PostgreSQL scope not affected.")
    if scope != "true":
        return Verification(False, f"invalid PostgreSQL scope output: {scope}")

    failed = [lane for lane in _LANES if values[f"{lane}_RESULT"] != "success"]
    if failed:
        return Verification(False, f"PostgreSQL lanes did not succeed: {', '.join(failed)}")
    missing_sha = [lane for lane in _LANES if not values.get(f"{lane}_SHA")]
    if missing_sha:
        return Verification(False, f"PostgreSQL lane SHA is missing: {', '.join(missing_sha)}")
    mismatched = [lane for lane in _LANES if values[f"{lane}_SHA"] != expected_sha]
    if mismatched:
        return Verification(False, f"PostgreSQL lane SHA mismatch: {', '.join(mismatched)}")
    mismatched_source = [
        lane
        for lane in _LANES
        if values[f"{lane}_SOURCE_SHA"] != expected_source_sha
    ]
    if mismatched_source:
        return Verification(
            False,
            f"PostgreSQL lane source SHA mismatch: {', '.join(mismatched_source)}",
        )
    return Verification(True, "Required PostgreSQL lanes are valid.")


def main() -> int:
    result = verify(os.environ)
    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
