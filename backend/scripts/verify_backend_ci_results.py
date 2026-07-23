"""Fail-closed state machine for the stable Backend required check."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Verification:
    ok: bool
    message: str


_REQUIRED_FIELDS = {
    "SCOPE_RESULT",
    "BACKEND_FROZEN_SCOPE",
    "WINDOWS_SCOPE",
    "BACKEND_CONTRACTS_RESULT",
    "BACKEND_FROZEN_RESULT",
    "WINDOWS_PACKAGING_RESULT",
    "EXPECTED_SHA",
    "EXPECTED_SOURCE_SHA",
    "AGGREGATOR_SHA",
    "AGGREGATOR_SOURCE_SHA",
    "SCOPE_SHA",
    "SCOPE_SOURCE_SHA",
    "BACKEND_CONTRACTS_SHA",
    "BACKEND_CONTRACTS_SOURCE_SHA",
}
_OPTIONAL_FIELDS = {
    "BACKEND_FROZEN_SHA",
    "BACKEND_FROZEN_SOURCE_SHA",
    "WINDOWS_PACKAGING_SHA",
    "WINDOWS_PACKAGING_SOURCE_SHA",
}
_SCOPED_JOBS = (
    (
        "Frozen backend",
        "BACKEND_FROZEN_SCOPE",
        "BACKEND_FROZEN_RESULT",
        "BACKEND_FROZEN_SHA",
        "BACKEND_FROZEN_SOURCE_SHA",
    ),
    (
        "Windows packaging",
        "WINDOWS_SCOPE",
        "WINDOWS_PACKAGING_RESULT",
        "WINDOWS_PACKAGING_SHA",
        "WINDOWS_PACKAGING_SOURCE_SHA",
    ),
)


def _missing_fields(values: Mapping[str, str]) -> list[str]:
    return sorted(
        {key for key in _REQUIRED_FIELDS if not values.get(key)}
        | {key for key in _OPTIONAL_FIELDS if key not in values}
    )


def _validate_required_jobs(values: Mapping[str, str]) -> Verification | None:
    for key, failure in (
        ("SCOPE_RESULT", "CI scope resolution did not succeed"),
        ("BACKEND_CONTRACTS_RESULT", "Backend contracts did not succeed"),
    ):
        if values[key] != "success":
            return Verification(False, f"{failure}: {values[key]}")
    return None


def _validate_sha_fields(
    values: Mapping[str, str],
    *,
    keys: tuple[str, ...],
    expected: str,
    label: str,
) -> Verification | None:
    for key in keys:
        if values[key] != expected:
            return Verification(False, f"{label} mismatch: {key}={values[key]}")
    return None


def _validate_scoped_job(
    values: Mapping[str, str],
    *,
    label: str,
    scope_key: str,
    result_key: str,
    sha_key: str,
    source_sha_key: str,
) -> Verification | None:
    scope = values[scope_key]
    result = values[result_key]
    reported_sha = values.get(sha_key, "")
    reported_source_sha = values.get(source_sha_key, "")
    if scope == "false":
        if result != "skipped":
            return Verification(False, f"{label} ran outside scope: {result}")
        if reported_sha or reported_source_sha:
            return Verification(False, f"skipped {label} reported a SHA")
        return None
    if scope != "true":
        return Verification(False, f"invalid {label} scope output: {scope}")
    if result != "success":
        return Verification(False, f"{label} did not succeed: {result}")
    if reported_sha != values["EXPECTED_SHA"]:
        return Verification(False, f"{label} SHA mismatch: {reported_sha}")
    if reported_source_sha != values["EXPECTED_SOURCE_SHA"]:
        return Verification(False, f"{label} source SHA mismatch: {reported_source_sha}")
    return None


def verify(values: Mapping[str, str]) -> Verification:
    missing = _missing_fields(values)
    if missing:
        return Verification(False, f"missing Backend CI result fields: {', '.join(missing)}")
    required_jobs = _validate_required_jobs(values)
    if required_jobs is not None:
        return required_jobs

    for check in (
        _validate_sha_fields(
            values,
            keys=("AGGREGATOR_SHA", "SCOPE_SHA", "BACKEND_CONTRACTS_SHA"),
            expected=values["EXPECTED_SHA"],
            label="qualification SHA",
        ),
        _validate_sha_fields(
            values,
            keys=(
                "AGGREGATOR_SOURCE_SHA",
                "SCOPE_SOURCE_SHA",
                "BACKEND_CONTRACTS_SOURCE_SHA",
            ),
            expected=values["EXPECTED_SOURCE_SHA"],
            label="qualification source SHA",
        ),
    ):
        if check is not None:
            return check

    for label, scope_key, result_key, sha_key, source_sha_key in _SCOPED_JOBS:
        check = _validate_scoped_job(
            values,
            label=label,
            scope_key=scope_key,
            result_key=result_key,
            sha_key=sha_key,
            source_sha_key=source_sha_key,
        )
        if check is not None:
            return check
    return Verification(True, "Required Backend CI results are valid.")


def main() -> int:
    result = verify(os.environ)
    print(result.message, file=sys.stdout if result.ok else sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
