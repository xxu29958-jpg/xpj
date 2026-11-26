"""Request/result serialization shared by the supported Lifecycle command entries."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, RESULT_SCHEMA, CommandResult, InstallRequest

_ALLOWED_EXISTING_RESULT_SCHEMAS = frozenset({
    RESULT_SCHEMA,
    "ticketbox-lifecycle-result-v1",
})


def resolve_default_forbidden_roots(
    *,
    install_root_fn: Callable[[], Path],
    program_data_root_fn: Callable[[], Path],
    allow_non_windows: bool = False,
) -> tuple[Path | None, Path | None, list[Path]]:
    if allow_non_windows and os.name != "nt":
        install_root: Path | None = None
        program_data_root: Path | None = None
        install_err: Exception | None = None
        pd_err: Exception | None = None
        try:
            install_root = install_root_fn()
        except Exception as exc:
            install_err = exc
        try:
            program_data_root = program_data_root_fn()
        except Exception as exc:
            pd_err = exc
        if (
            install_err is not None
            and pd_err is not None
            and isinstance(install_err, LifecycleError)
            and install_err.code == "windows_required"
            and isinstance(pd_err, LifecycleError)
            and pd_err.code == "windows_required"
        ):
            return None, None, []
        if install_err is not None or pd_err is not None or install_root is None or program_data_root is None:
            raise LifecycleViolation(
                "forbidden_roots_unavailable",
                "cannot resolve protected installation and ProgramData roots; refusing to write result output",
            ) from (install_err or pd_err)
        return install_root, program_data_root, [
            install_root,
            program_data_root,
            program_data_root / "data",
            program_data_root / "backups",
        ]
    try:
        install_root = install_root_fn()
        program_data_root = program_data_root_fn()
    except Exception as exc:
        raise LifecycleViolation(
            "forbidden_roots_unavailable",
            "cannot resolve protected installation and ProgramData roots; refusing to write result output",
        ) from exc
    return install_root, program_data_root, [
        install_root,
        program_data_root,
        program_data_root / "data",
        program_data_root / "backups",
    ]


def _norm_abs(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_same_or_under(target: str, root: str) -> bool:
    if target == root:
        return True
    prefix = root if root.endswith(os.sep) else root + os.sep
    return target.startswith(prefix)


def require_safe_result_path(
    path: Path,
    *,
    forbidden_roots: Iterable[Path] = (),
    protected_files: Iterable[Path] = (),
) -> None:
    """Refuse backup/archive/in-tree or non-result targets before writing any byte."""
    reject_reparse_components(path)
    if path.suffix.lower() != ".json":
        raise LifecycleViolation(
            "unsafe_result_path",
            "lifecycle result path must use a .json filename outside backup and installation roots",
        )
    target_key = _norm_abs(path)
    for protected in protected_files:
        if not os.fspath(protected):
            continue
        if target_key == _norm_abs(protected):
            raise LifecycleViolation(
                "unsafe_result_path",
                "refusing to overwrite a protected backup or source file with lifecycle result output",
            )
    for root in forbidden_roots:
        if not os.fspath(root):
            continue
        if _is_same_or_under(target_key, _norm_abs(root)):
            raise LifecycleViolation(
                "unsafe_result_path",
                "lifecycle result path must lie outside installation, data, machine and backup directories",
            )
    if os.path.lexists(path):
        if path.is_dir() or not path.is_file():
            raise LifecycleViolation(
                "unsafe_result_path",
                "lifecycle result destination must be a regular file",
            )
        raw = path.read_bytes()
        if not raw or len(raw) > 65536:
            raise LifecycleViolation(
                "unsafe_result_path",
                "refusing to overwrite an existing empty or non-result file",
            )
        try:
            existing = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise LifecycleViolation(
                "unsafe_result_path",
                "refusing to overwrite an existing non-result file",
            ) from exc
        if (
            not isinstance(existing, dict)
            or existing.get("schema") not in _ALLOWED_EXISTING_RESULT_SCHEMAS
        ):
            raise LifecycleViolation(
                "unsafe_result_path",
                "refusing to overwrite an existing non-result JSON file",
            )


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
    require_safe_result_path(path)
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


def write_result_if_safe(
    path: Path,
    result: CommandResult,
    *,
    forbidden_roots: Iterable[Path] = (),
    protected_files: Iterable[Path] = (),
) -> bool:
    try:
        require_safe_result_path(
            path,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
        )
    except LifecycleError:
        return False
    write_result(path, result)
    return True


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
