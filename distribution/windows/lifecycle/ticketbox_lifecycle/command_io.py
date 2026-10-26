"""Request/result serialization shared by the supported Lifecycle command entries."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, CommandResult, InstallRequest


def emit_failure(result: CommandResult) -> None:
    message = " ".join(result.message.split())
    message = re.sub(r"(?<!\d)\d{8}(?!\d)", "[redacted]", message)
    message = re.sub(
        r"(?i)(PASSWORD\s+')[^']*(')",
        r"\1[redacted]\2",
        message,
    )
    if len(message) > 800:
        message = message[:797] + "..."
    print(
        f"TicketboxLifecycle failed [{result.code}]: {message}",
        file=sys.stderr,
        flush=True,
    )


def write_result(path: Path, result: CommandResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(asdict(result), indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def parse_request(payload: dict[str, object], *, command: str) -> InstallRequest:
    if payload.get("schema") != REQUEST_SCHEMA:
        raise LifecycleError("bad_request_schema", "request schema is not ticketbox-lifecycle-request-v1")
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command=command,  # type: ignore[arg-type]
        operation_id=str(payload["operation_id"]),
        request_hash=str(payload["request_hash"]),
        target_release_id=str(payload["target_release_id"]),
        app_dir=str(payload["app_dir"]),
        data_root=str(payload["data_root"]),
        program_data_root=str(payload["program_data_root"]),
        pg_service_name=str(payload["pg_service_name"]),
        backend_service_name=str(payload["backend_service_name"]),
        pg_port=int(payload["pg_port"]),
        backend_port=int(payload["backend_port"]),
        postgres_major=int(payload["postgres_major"]),
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
    )
