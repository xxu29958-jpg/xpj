from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import stat
import struct
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dependency_check_contract import (
    MAX_FUTURE_SKEW_SECONDS,
    PAYLOAD_TTL_SECONDS,
    SHA256_PATTERN,
    assert_secret_absent,
    dependency_check_version,
    load_json,
    producer_contract_sha256,
    require_integer,
    require_mapping,
    require_nonempty_string,
    repository_root,
    version_catalog_path,
)
from verify_dependency_check_report import verify_report

MANIFEST_NAME = "xpj-nvd-payload-manifest.json"
_MANIFEST_SCHEMA = 2
_PAYLOAD_ALGORITHM = "sha256-tree-v1"
_PRODUCER_REFRESH_SKEW_SECONDS = 5


@dataclass(frozen=True)
class PayloadIdentity:
    file_count: int
    total_bytes: int
    sha256: str


@dataclass(frozen=True)
class VerifiedPayload:
    refreshed_at_epoch: int
    expires_at_epoch: int
    payload: PayloadIdentity


def _payload_files(data_dir: Path) -> list[tuple[str, Path]]:
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise ValueError("OWASP NVD data path must be a real directory")

    files: list[tuple[str, Path]] = []
    for path in sorted(
        data_dir.rglob("*"),
        key=lambda candidate: candidate.relative_to(data_dir).as_posix(),
    ):
        relative = path.relative_to(data_dir).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"OWASP NVD payload contains a symlink: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"OWASP NVD payload contains a non-regular entry: {relative}"
            )
        if relative == MANIFEST_NAME:
            continue
        files.append((relative, path))
    return files


def _hash_file(path: Path) -> tuple[int, bytes]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        raise ValueError(f"OWASP NVD payload changed while hashing: {path.name}")
    return after.st_size, digest.digest()


def payload_identity(data_dir: Path) -> PayloadIdentity:
    files = _payload_files(data_dir)
    if not files:
        raise ValueError("OWASP NVD payload contains no files")

    tree_digest = hashlib.sha256()
    tree_digest.update(b"xpj-nvd-payload\0sha256-tree-v1\0")
    total_bytes = 0
    for relative, path in files:
        relative_bytes = relative.encode("utf-8")
        size, file_digest = _hash_file(path)
        tree_digest.update(struct.pack(">Q", len(relative_bytes)))
        tree_digest.update(relative_bytes)
        tree_digest.update(struct.pack(">Q", size))
        tree_digest.update(file_digest)
        total_bytes += size
    if total_bytes <= 0:
        raise ValueError("OWASP NVD payload contains no non-empty data")
    return PayloadIdentity(
        file_count=len(files),
        total_bytes=total_bytes,
        sha256=tree_digest.hexdigest(),
    )


def _manifest_document(
    *,
    version: str,
    contract_digest: str,
    refreshed_at_epoch: int,
    payload: PayloadIdentity,
) -> dict[str, object]:
    return {
        "schema": _MANIFEST_SCHEMA,
        "dependency_check_version": version,
        "producer_contract_sha256": contract_digest,
        "refreshed_at_epoch": refreshed_at_epoch,
        "expires_at_epoch": refreshed_at_epoch + PAYLOAD_TTL_SECONDS,
        "payload": {
            "algorithm": _PAYLOAD_ALGORITHM,
            "file_count": payload.file_count,
            "total_bytes": payload.total_bytes,
            "sha256": payload.sha256,
        },
    }


def _atomic_write_json(path: Path, document: dict[str, object]) -> None:
    temporary = path.with_name(
        f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        stream = os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        )
        descriptor = -1
        with stream:
            json.dump(
                document,
                stream,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def create_manifest(
    data_dir: Path,
    *,
    report_path: Path,
    catalog_path: Path,
    nvd_checked_after_epoch: int,
) -> PayloadIdentity:
    report_identity = verify_report(report_path, catalog_path=catalog_path)
    if (
        report_identity.nvd_checked_epoch + _PRODUCER_REFRESH_SKEW_SECONDS
        < nvd_checked_after_epoch
    ):
        raise ValueError("NVD metadata was not refreshed by this producer run")
    payload = payload_identity(data_dir)
    document = _manifest_document(
        version=dependency_check_version(catalog_path),
        contract_digest=producer_contract_sha256(repository_root()),
        refreshed_at_epoch=report_identity.nvd_checked_epoch,
        payload=payload,
    )
    _atomic_write_json(data_dir / MANIFEST_NAME, document)
    return payload


def _manifest_identity(manifest: dict[str, object]) -> PayloadIdentity:
    payload_document = require_mapping(
        manifest["payload"],
        label="manifest payload identity",
    )
    if set(payload_document) != {
        "algorithm",
        "file_count",
        "total_bytes",
        "sha256",
    }:
        raise ValueError("OWASP NVD payload identity shape is invalid")
    if payload_document["algorithm"] != _PAYLOAD_ALGORITHM:
        raise ValueError("OWASP NVD payload digest algorithm is unsupported")
    identity = PayloadIdentity(
        file_count=require_integer(
            payload_document["file_count"],
            label="manifest payload file_count",
        ),
        total_bytes=require_integer(
            payload_document["total_bytes"],
            label="manifest payload total_bytes",
        ),
        sha256=require_nonempty_string(
            payload_document["sha256"],
            label="manifest payload sha256",
        ),
    )
    if SHA256_PATTERN.fullmatch(identity.sha256) is None:
        raise ValueError("OWASP NVD payload digest is invalid")
    return identity


def verify_manifest(
    data_dir: Path,
    *,
    catalog_path: Path,
    now_epoch: int | None = None,
    allow_expired: bool = False,
    minimum_refreshed_at_epoch: int = 0,
    expected_refreshed_at_epoch: int | None = None,
    expected_payload_sha256: str | None = None,
) -> VerifiedPayload:
    manifest_path = data_dir / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("OWASP NVD payload manifest is missing or unsafe")
    if manifest_path.stat().st_size > 64 * 1024:
        raise ValueError("OWASP NVD payload manifest is unexpectedly large")

    manifest = load_json(manifest_path, label="OWASP NVD payload manifest")
    expected_keys = {
        "schema",
        "dependency_check_version",
        "producer_contract_sha256",
        "refreshed_at_epoch",
        "expires_at_epoch",
        "payload",
    }
    if set(manifest) != expected_keys:
        raise ValueError("OWASP NVD payload manifest shape is invalid")
    if require_integer(manifest["schema"], label="manifest schema") != (
        _MANIFEST_SCHEMA
    ):
        raise ValueError("OWASP NVD payload manifest schema is unsupported")
    if manifest["dependency_check_version"] != dependency_check_version(
        catalog_path
    ):
        raise ValueError("OWASP NVD payload version does not match this checkout")
    contract_digest = manifest["producer_contract_sha256"]
    expected_contract_digest = producer_contract_sha256(repository_root())
    if (
        not isinstance(contract_digest, str)
        or SHA256_PATTERN.fullmatch(contract_digest) is None
        or not hmac.compare_digest(contract_digest, expected_contract_digest)
    ):
        raise ValueError("OWASP NVD producer contract does not match this checkout")

    refreshed_at = require_integer(
        manifest["refreshed_at_epoch"],
        label="manifest refreshed_at_epoch",
    )
    expires_at = require_integer(
        manifest["expires_at_epoch"],
        label="manifest expires_at_epoch",
    )
    if expires_at - refreshed_at != PAYLOAD_TTL_SECONDS:
        raise ValueError("OWASP NVD payload freshness window is invalid")
    current_time = int(time.time()) if now_epoch is None else now_epoch
    if refreshed_at > current_time + MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("OWASP NVD payload refresh time is in the future")
    if not allow_expired and expires_at <= current_time:
        raise ValueError("OWASP NVD payload has expired")
    if minimum_refreshed_at_epoch < 0:
        raise ValueError("minimum NVD refresh time cannot be negative")
    if refreshed_at < minimum_refreshed_at_epoch:
        raise ValueError("OWASP NVD payload would move certified freshness backward")
    if (
        expected_refreshed_at_epoch is not None
        and (
            expected_refreshed_at_epoch < 0
            or refreshed_at != expected_refreshed_at_epoch
        )
    ):
        raise ValueError("OWASP NVD payload freshness differs from the certified candidate")

    expected_identity = _manifest_identity(manifest)
    actual_identity = payload_identity(data_dir)
    if (
        actual_identity.file_count != expected_identity.file_count
        or actual_identity.total_bytes != expected_identity.total_bytes
        or not hmac.compare_digest(
            actual_identity.sha256,
            expected_identity.sha256,
        )
    ):
        raise ValueError("OWASP NVD payload content does not match its manifest")
    if (
        expected_payload_sha256 is not None
        and (
            SHA256_PATTERN.fullmatch(expected_payload_sha256) is None
            or not hmac.compare_digest(
                actual_identity.sha256,
                expected_payload_sha256,
            )
        )
    ):
        raise ValueError("OWASP NVD payload differs from the certified candidate")
    return VerifiedPayload(
        refreshed_at_epoch=refreshed_at,
        expires_at_epoch=expires_at,
        payload=actual_identity,
    )


def _write_github_output(path: Path, verified: VerifiedPayload) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"refreshed-at-epoch={verified.refreshed_at_epoch}\n")
        stream.write(f"expires-at-epoch={verified.expires_at_epoch}\n")
        stream.write(f"payload-sha256={verified.payload.sha256}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--version-catalog", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--nvd-checked-after-epoch", type=int)
    parser.add_argument("--allow-expired", action="store_true")
    parser.add_argument("--minimum-refreshed-at-epoch", type=int, default=0)
    parser.add_argument("--expected-refreshed-at-epoch", type=int)
    parser.add_argument("--expected-payload-sha256")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    assert_secret_absent()
    catalog_path = args.version_catalog or version_catalog_path()
    if args.command == "create":
        if (
            args.report is None
            or args.nvd_checked_after_epoch is None
            or args.allow_expired
            or args.minimum_refreshed_at_epoch != 0
            or args.expected_refreshed_at_epoch is not None
            or args.expected_payload_sha256 is not None
            or args.github_output is not None
        ):
            raise ValueError(
                "create accepts only --report and --nvd-checked-after-epoch"
            )
        identity = create_manifest(
            args.data_dir,
            report_path=args.report,
            catalog_path=catalog_path,
            nvd_checked_after_epoch=args.nvd_checked_after_epoch,
        )
        status = "NVD_PAYLOAD_MANIFEST_CREATED"
    else:
        if args.report is not None or args.nvd_checked_after_epoch is not None:
            raise ValueError("verify does not accept report creation arguments")
        verified = verify_manifest(
            args.data_dir,
            catalog_path=catalog_path,
            allow_expired=args.allow_expired,
            minimum_refreshed_at_epoch=args.minimum_refreshed_at_epoch,
            expected_refreshed_at_epoch=args.expected_refreshed_at_epoch,
            expected_payload_sha256=args.expected_payload_sha256,
        )
        if args.github_output is not None:
            _write_github_output(args.github_output, verified)
        identity = verified.payload
        status = "NVD_PAYLOAD_MANIFEST_VERIFIED"
    print(
        f"{status} files={identity.file_count} "
        f"bytes={identity.total_bytes} sha256={identity.sha256}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
