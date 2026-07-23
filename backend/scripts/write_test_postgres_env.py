"""Create a short-lived CI passfile and render sealed PostgreSQL URLs."""

from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import quote, urlencode

if __package__:
    from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
else:
    from test_postgres_contract import TEST_POSTGRES_CONTRACT


def _loopback_hostaddr(host: str, port: int) -> str:
    addresses = {
        ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    }
    if not addresses or any(not address.is_loopback for address in addresses):
        raise ValueError("test PostgreSQL host must resolve exclusively to loopback")
    return str(min(addresses, key=lambda address: (address.version != 4, int(address))))


def _url(
    *,
    host: str,
    hostaddr: str,
    port: int,
    user: str,
    database: str,
    authentication: str,
) -> str:
    query = urlencode(
        {
            "connect_timeout": "5",
            "hostaddr": hostaddr,
            "options": "-csearch_path=public,pg_catalog",
            "require_auth": authentication,
            "sslmode": "disable",
        }
    )
    return (
        f"postgresql+psycopg://{quote(user, safe='')}@{host}:{port}/"
        f"{quote(database, safe='')}?{query}"
    )


def _escape_passfile(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def write_passfile(
    path: Path,
    *,
    host: str,
    port: int,
    admin_user: str,
    admin_password: str,
    application_user: str,
    application_password: str,
) -> None:
    credentials = (
        (admin_user, admin_password),
        (application_user, application_password),
    )
    if len({user for user, _password in credentials}) != len(credentials):
        raise ValueError("test PostgreSQL roles must be distinct")
    if any(
        not user
        or not password
        or "\n" in user
        or "\r" in user
        or "\n" in password
        or "\r" in password
        for user, password in credentials
    ):
        raise ValueError("test PostgreSQL credential is empty or multiline")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        ":".join(
            _escape_passfile(value)
            for value in (host, str(port), "*", user, password)
        )
        for user, password in credentials
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    durable = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write("".join(f"{line}\n" for line in lines))
            output.flush()
            os.fsync(output.fileno())
        durable = True
    finally:
        if not durable:
            path.unlink(missing_ok=True)

    permissions_sealed = False
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        permissions_sealed = True
    finally:
        if not permissions_sealed:
            path.unlink(missing_ok=True)


def existing_passfile(path: Path) -> Path:
    """Accept an already-sealed passfile without reading its secret in Python."""
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not stat.S_ISREG(os.lstat(path).st_mode):
        raise ValueError("existing PostgreSQL passfile must be a regular file")
    return resolved


def render_environment(
    *,
    host: str,
    port: int,
    admin_user: str,
    application_user: str,
    passfile: Path | None,
    cluster_identity: str,
    authentication: str = "scram-sha-256",
) -> dict[str, str]:
    if authentication not in {"none", "scram-sha-256"}:
        raise ValueError("unsupported test PostgreSQL authentication contract")
    if authentication == "scram-sha-256" and passfile is None:
        raise ValueError("SCRAM test PostgreSQL requires a passfile")
    if authentication == "none" and passfile is not None:
        raise ValueError("no-challenge test PostgreSQL must not receive a passfile")
    contract = TEST_POSTGRES_CONTRACT
    cluster_identity = contract.require_database_identity(cluster_identity)
    port = contract.require_allowed_host_port(port)
    hostaddr = _loopback_hostaddr(host, port)
    names = {
        "base_database": contract.base_database,
        "smoke_database": contract.smoke_database,
        "restore_database": contract.restore_database,
    }
    urls = {
        role: _url(
            host=host,
            hostaddr=hostaddr,
            port=port,
            user=application_user,
            database=database,
            authentication=authentication,
        )
        for role, database in names.items()
    }
    admin_url = _url(
        host=host,
        hostaddr=hostaddr,
        port=port,
        user=admin_user,
        database="postgres",
        authentication=authentication,
    )
    values = {
        "XPJ_TEST_BASE_DATABASE": names["base_database"],
        "XPJ_TEST_SMOKE_DATABASE": names["smoke_database"],
        "XPJ_TEST_RESTORE_DATABASE": names["restore_database"],
        "XPJ_TEST_APPLICATION_ROLE": application_user,
        "XPJ_TEST_CLUSTER_IDENTITY": cluster_identity,
        "XPJ_TEST_ADMIN_URL": admin_url,
        "XPJ_TEST_DATABASE_URL": urls["base_database"],
        "SMOKE_DATABASE_URL": urls["smoke_database"],
        "DRILL_SOURCE_URL": urls["smoke_database"],
        "DRILL_RESTORE_URL": urls["restore_database"],
    }
    if passfile is not None:
        values["PGPASSFILE"] = str(passfile.resolve())
    return values


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    port = parser.add_mutually_exclusive_group(required=True)
    port.add_argument("--port", type=int)
    port.add_argument("--port-profile", choices=("gitea", "local"))
    parser.add_argument("--admin-user", required=True)
    parser.add_argument(
        "--application-user",
        default=TEST_POSTGRES_CONTRACT.application_role,
    )
    parser.add_argument(
        "--authentication",
        choices=("none", "scram-sha-256"),
        default="scram-sha-256",
    )
    parser.add_argument("--admin-password-env")
    parser.add_argument("--application-password-env")
    parser.add_argument("--passfile", type=Path)
    parser.add_argument("--existing-passfile", type=Path)
    parser.add_argument("--cluster-identity")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    port = (
        args.port
        if args.port is not None
        else TEST_POSTGRES_CONTRACT.ports.for_profile(args.port_profile)
    )
    scram = args.authentication == "scram-sha-256"
    password_envs = (
        args.admin_password_env,
        args.application_password_env,
    )
    creates_passfile = any(value is not None for value in password_envs) or args.passfile is not None
    uses_existing_passfile = args.existing_passfile is not None
    if creates_passfile and not (all(value is not None for value in password_envs) and args.passfile is not None):
        raise RuntimeError("both password env names and passfile must be supplied together")
    if not scram and (creates_passfile or uses_existing_passfile):
        raise RuntimeError("no-challenge authentication forbids passfiles")
    if scram and creates_passfile == uses_existing_passfile:
        raise RuntimeError("SCRAM requires exactly one passfile source")
    resolved_passfile = None
    if creates_passfile:
        passwords = {
            name: os.environ.get(name)
            for name in password_envs
            if name is not None
        }
        missing = [name for name, value in passwords.items() if value is None]
        if missing:
            raise RuntimeError(
                "password environment variable is missing: " + ", ".join(missing)
            )
        write_passfile(
            args.passfile,
            host=args.host,
            port=port,
            admin_user=args.admin_user,
            admin_password=passwords[args.admin_password_env],
            application_user=args.application_user,
            application_password=passwords[args.application_password_env],
        )
        resolved_passfile = args.passfile
    elif uses_existing_passfile:
        resolved_passfile = existing_passfile(args.existing_passfile)
    if args.cluster_identity is not None:
        cluster_identity = TEST_POSTGRES_CONTRACT.require_database_identity(args.cluster_identity)
    elif args.port_profile == "local" and uses_existing_passfile:
        cluster_identity = TEST_POSTGRES_CONTRACT.local_database_identity(port)
    else:
        cluster_identity = TEST_POSTGRES_CONTRACT.database_identity(str(uuid.uuid4()))
    environment_published = False
    try:
        values = render_environment(
            host=args.host,
            port=port,
            admin_user=args.admin_user,
            application_user=args.application_user,
            passfile=resolved_passfile,
            cluster_identity=cluster_identity,
            authentication=args.authentication,
        )
        invalid_keys = [key for key, value in values.items() if "\n" in value or "\r" in value]
        if invalid_keys:
            raise RuntimeError(
                f"invalid multiline environment value: {', '.join(sorted(invalid_keys))}"
            )
        with args.output.open("a", encoding="utf-8", newline="\n") as output:
            for key, value in values.items():
                output.write(f"{key}={value}\n")
        environment_published = True
    finally:
        if not environment_published and creates_passfile:
            args.passfile.unlink(missing_ok=True)
    print("Loaded the test PostgreSQL contract into the CI environment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
