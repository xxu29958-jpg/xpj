"""Run one complete PostgreSQL pytest responsibility lane.

The workflow chooses only the lane and bounded worker count. This module owns
the pytest selection and safety flags so GitHub, Gitea, local execution, and
the CI audit cannot drift into separate command contracts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy.engine import make_url

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.write_test_postgres_env import render_environment

_PYTEST_CONTRACT_ARGS = (
    "-q",
    "-ra",
    "--tb=short",
    "-p",
    "no:cacheprovider",
    "--strict-markers",
    "-o",
    "addopts=",
)
POSTGRES_PYTEST_LANE_OPTION = "--xpj-postgres-lane"
POSTGRES_PYTEST_LANE_DEST = "xpj_postgres_lane"
POSTGRES_PYTEST_LANE_MARKERS = {
    "ordinary": "not real_db",
    "real-db": "real_db",
}
PARALLEL_POSTGRES_PYTEST_LANE = "ordinary"
_LIBPQ_ROUTE_ENV = {
    "PGAPPNAME",
    "PGDATABASE",
    "PGHOST",
    "PGHOSTADDR",
    "PGOPTIONS",
    "PGPASSWORD",
    "PGPORT",
    "PGREQUIREAUTH",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSSLMODE",
    "PGUSER",
    "TEST_POSTGRES_PASSWORD",
    "TEST_POSTGRES_APPLICATION_PASSWORD",
    "XPJ_TEST_APPLICATION_PASSWORD",
}


def build_pytest_command(*, lane: str, workers: int) -> tuple[str, ...]:
    if lane not in POSTGRES_PYTEST_LANE_MARKERS:
        raise ValueError(f"unknown PostgreSQL pytest lane: {lane}")
    if workers < 1 or workers > 4:
        raise ValueError("PostgreSQL pytest workers must be between 1 and 4")
    if lane == "real-db" and workers != 1:
        raise ValueError("the real-db PostgreSQL lane must remain serial")

    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        *_PYTEST_CONTRACT_ARGS,
        POSTGRES_PYTEST_LANE_OPTION,
        lane,
        "-m",
        POSTGRES_PYTEST_LANE_MARKERS[lane],
    ]
    if workers > 1:
        command.extend(
            (
                "-n",
                str(workers),
                "--dist",
                "worksteal",
                "--max-worker-restart=0",
            )
        )
    return tuple(command)


def build_pytest_collection_command(target: str) -> tuple[str, ...]:
    if not target or target.startswith("-"):
        raise ValueError("pytest collection target must be an explicit path")
    return (
        sys.executable,
        "-m",
        "pytest",
        target,
        "--collect-only",
        *_PYTEST_CONTRACT_ARGS,
    )


def validate_lane_collection(
    *,
    lane: str | None,
    selected_real_db: Sequence[bool],
) -> None:
    """Reject empty or cross-lane collections without a second test inventory."""
    if lane is None:
        return
    if lane not in POSTGRES_PYTEST_LANE_MARKERS:
        raise ValueError(f"unknown PostgreSQL pytest lane: {lane}")
    if not selected_real_db:
        raise ValueError(f"the {lane} PostgreSQL lane selected no tests")
    if lane == "ordinary" and any(selected_real_db):
        raise ValueError(
            "the ordinary PostgreSQL lane selected a real_db test; "
            "the lane runner and marker selection have drifted"
        )
    if lane == "real-db" and not all(selected_real_db):
        raise ValueError(
            "the real-db PostgreSQL lane selected an ordinary test; "
            "the lane runner and marker selection have drifted"
        )


def child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Remove ambient libpq routing and preserve only contract-required secrets."""
    environment = dict(source)
    for key in _LIBPQ_ROUTE_ENV:
        environment.pop(key, None)
    raw_url = source.get("XPJ_TEST_DATABASE_URL")
    raw_admin_url = source.get("XPJ_TEST_ADMIN_URL")
    if (raw_url is None) != (raw_admin_url is None):
        raise RuntimeError(
            "PostgreSQL lane requires XPJ_TEST_DATABASE_URL and "
            "XPJ_TEST_ADMIN_URL together"
        )
    authentication = "none"
    if raw_url is not None and raw_admin_url is not None:
        authentication = make_url(raw_url).query.get("require_auth")
        admin_authentication = make_url(raw_admin_url).query.get("require_auth")
        if authentication != admin_authentication:
            raise RuntimeError(
                "PostgreSQL lane database and admin URLs require the same authentication"
            )
    if authentication == "none":
        environment.pop("PGPASSFILE", None)
    elif authentication == "scram-sha-256":
        if not source.get("PGPASSFILE"):
            raise RuntimeError("SCRAM PostgreSQL lane requires a passfile")
    else:
        raise RuntimeError("PostgreSQL lane requires an explicit authentication contract")
    environment["PYTEST_ADDOPTS"] = ""
    return environment


def collection_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Build a non-connecting pytest collection context without a live cluster."""
    environment = child_environment(source)
    contract = TEST_POSTGRES_CONTRACT
    identity = contract.database_identity(
        str(uuid.uuid5(uuid.NAMESPACE_OID, f"{contract.cluster_marker}:collection"))
    )
    values = render_environment(
        host="localhost",
        port=contract.ports.local,
        admin_user="postgres",
        application_user=contract.application_role,
        passfile=contract.default_data_dir(contract.ports.local)
        / contract.passfile_name,
        cluster_identity=identity,
    )
    environment.update(
        {
            key: values[key]
            for key in (
                "XPJ_TEST_CLUSTER_IDENTITY",
                "XPJ_TEST_DATABASE_URL",
                "XPJ_TEST_ADMIN_URL",
            )
        }
    )
    environment.pop("PGPASSFILE", None)
    return environment


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lane",
        choices=tuple(POSTGRES_PYTEST_LANE_MARKERS),
        required=True,
    )
    parser.add_argument("--workers", type=int, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    command = build_pytest_command(lane=args.lane, workers=args.workers)
    return subprocess.run(
        command,
        check=False,
        env=child_environment(os.environ),
        shell=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
