"""Fail-closed verifier shared by scoped jobs and stable lane aggregators."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class Verification:
    ok: bool
    message: str


def _missing_fields(
    values: Mapping[str, str],
    *,
    scope_keys: Sequence[str],
    lanes: Sequence[str],
) -> list[str]:
    required = {
        "SCOPE_RESULT",
        *scope_keys,
        "EXPECTED_SHA",
        "EXPECTED_SOURCE_SHA",
        "AGGREGATOR_SHA",
        "AGGREGATOR_SOURCE_SHA",
        "SCOPE_SHA",
        "SCOPE_SOURCE_SHA",
        *(f"{lane}_RESULT" for lane in lanes),
    }
    lane_sha_keys = {f"{lane}_SHA" for lane in lanes}
    lane_source_sha_keys = {f"{lane}_SOURCE_SHA" for lane in lanes}
    return sorted(
        {key for key in required if not values.get(key)}
        | {
            key
            for key in lane_sha_keys | lane_source_sha_keys
            if key not in values
        }
    )


def _identity_failure(
    values: Mapping[str, str],
    label: str,
) -> Verification | None:
    if values["SCOPE_RESULT"] != "success":
        return Verification(
            False,
            f"{label} scope resolution did not succeed: {values['SCOPE_RESULT']}",
        )

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
    return None


def _verify_skipped_lanes(
    values: Mapping[str, str],
    label: str,
    lanes: Sequence[str],
) -> Verification:
    wrong = [lane for lane in lanes if values[f"{lane}_RESULT"] != "skipped"]
    if wrong:
        return Verification(
            False,
            f"{label} lanes ran outside scope: {', '.join(wrong)}",
        )
    reported_sha = [
        lane
        for lane in lanes
        if values.get(f"{lane}_SHA") or values.get(f"{lane}_SOURCE_SHA")
    ]
    if reported_sha:
        return Verification(
            False,
            f"skipped {label} lanes reported a SHA: {', '.join(reported_sha)}",
        )
    return Verification(True, f"{label} scope not affected.")


def _verify_required_lanes(
    values: Mapping[str, str],
    label: str,
    lanes: Sequence[str],
    source_lanes: Sequence[str],
) -> Verification:
    failed = [lane for lane in lanes if values[f"{lane}_RESULT"] != "success"]
    if failed:
        return Verification(
            False,
            f"{label} lanes did not succeed: {', '.join(failed)}",
        )
    expected_sha = values["EXPECTED_SHA"]
    exact_source_lanes = set(source_lanes)
    mismatched_sha = [
        lane
        for lane in lanes
        if values[f"{lane}_SHA"]
        != (
            values["EXPECTED_SOURCE_SHA"]
            if lane in exact_source_lanes
            else expected_sha
        )
    ]
    if mismatched_sha:
        return Verification(
            False,
            f"{label} lane SHA mismatch: {', '.join(mismatched_sha)}",
        )
    expected_source_sha = values["EXPECTED_SOURCE_SHA"]
    mismatched_source = [
        lane
        for lane in lanes
        if values[f"{lane}_SOURCE_SHA"] != expected_source_sha
    ]
    if mismatched_source:
        return Verification(
            False,
            f"{label} lane source SHA mismatch: {', '.join(mismatched_source)}",
        )
    return Verification(True, f"Required {label} lanes are valid.")


def _scope_failure(
    values: Mapping[str, str],
    label: str,
    scope_key: str,
    lane_scopes: Mapping[str, str],
) -> Verification | None:
    for key in {scope_key, *lane_scopes.values()}:
        if values[key] not in {"true", "false"}:
            return Verification(False, f"invalid {label} scope output: {key}={values[key]}")
    if values[scope_key] == "false" and any(values[key] == "true" for key in lane_scopes.values()):
        return Verification(False, f"{label} capability selected outside parent scope")
    return None


def _verify_scoped_lanes(
    values: Mapping[str, str],
    label: str,
    lane_scopes: Mapping[str, str],
    source_lanes: Sequence[str],
) -> Verification:
    required = [lane for lane, key in lane_scopes.items() if values[key] == "true"]
    skipped = [lane for lane, key in lane_scopes.items() if values[key] == "false"]
    result = _verify_required_lanes(values, label, required, source_lanes)
    if not result.ok:
        return result
    result = _verify_skipped_lanes(values, label, skipped)
    if not result.ok:
        return result
    return Verification(True, f"{label} lanes valid: required={','.join(required) or '(none)'}; not affected={','.join(skipped) or '(none)'}")


def verify(
    values: Mapping[str, str],
    *,
    label: str,
    scope_key: str,
    lanes: Sequence[str],
    source_lanes: Sequence[str],
    lane_scopes: Mapping[str, str] | None = None,
) -> Verification:
    if not set(source_lanes).issubset(lanes):
        return Verification(False, "source lanes must also be required lanes")
    overrides = lane_scopes or {}
    if not set(overrides).issubset(lanes):
        return Verification(False, "scope overrides must name declared lanes")
    resolved = {lane: overrides.get(lane, scope_key) for lane in lanes}
    missing = _missing_fields(values, scope_keys=(scope_key, *resolved.values()), lanes=lanes)
    if missing:
        return Verification(
            False,
            f"missing {label} CI result fields: {', '.join(missing)}",
        )
    identity_failure = _identity_failure(values, label)
    if identity_failure is not None:
        return identity_failure

    scope_failure = _scope_failure(values, label, scope_key, resolved)
    if scope_failure is not None:
        return scope_failure
    return _verify_scoped_lanes(values, label, resolved, source_lanes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--scope-key", required=True)
    parser.add_argument("--lane", action="append", default=[])
    parser.add_argument("--source-lane", action="append", default=[])
    parser.add_argument("--lane-scope", action="append", default=[], metavar="LANE=SCOPE_KEY")
    return parser


def _parse_lane_scopes(
    parser: argparse.ArgumentParser, bindings: Sequence[str], lanes: Sequence[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for binding in bindings:
        lane, separator, key = binding.partition("=")
        if not separator or lane not in lanes or lane in result or not _ENV_KEY.fullmatch(key):
            parser.error("lane scope must uniquely bind a declared lane to an uppercase environment key")
        result[lane] = key
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    lanes = tuple(args.lane)
    source_lanes = tuple(args.source_lane)
    if (
        not _ENV_KEY.fullmatch(args.scope_key)
        or any(_ENV_KEY.fullmatch(lane) is None for lane in lanes)
        or any(_ENV_KEY.fullmatch(lane) is None for lane in source_lanes)
        or len(set(lanes)) != len(lanes)
        or len(set(source_lanes)) != len(source_lanes)
        or not set(source_lanes).issubset(lanes)
    ):
        parser.error(
            "scope key and lanes must be unique uppercase environment keys; "
            "source lanes must also be required lanes"
        )
    result = verify(
        os.environ,
        label=args.label,
        scope_key=args.scope_key,
        lanes=lanes,
        source_lanes=source_lanes,
        lane_scopes=_parse_lane_scopes(parser, args.lane_scope, lanes),
    )
    print(result.message, file=sys.stdout if result.ok else sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
