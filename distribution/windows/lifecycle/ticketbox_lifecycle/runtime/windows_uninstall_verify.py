"""Owned-service/connector verification and release-manifest inspection helpers for uninstall."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from ticketbox_lifecycle.adapters.scm import ScmObserver
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME as CONNECTOR_SERVICE_NAME
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    SERVICE_DEMAND_START,
    expected_backend_service,
    expected_pg_service,
    require_service_configuration,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import service_exists
from ticketbox_lifecycle.runtime.windows_shipment import _expected_files, _parse_manifest
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest

_CONNECTOR_TOKEN_FILE = re.compile(r"credential-g[1-9][0-9]*\.token\Z", re.IGNORECASE)


def _norm_path(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(value)))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _raise_walk_error(exc: OSError) -> None:
    raise LifecycleViolation(
        "uninstall_release_unreadable",
        f"cannot enumerate release directory during uninstall: {exc.filename or exc}",
    ) from exc


def _is_path_inside_dir(candidate: str, directory: Path) -> bool:
    if not candidate:
        return False
    cand_path = Path(os.path.abspath(candidate))
    dir_path = Path(os.path.abspath(directory))
    try:
        cand_path.relative_to(dir_path)
        return True
    except ValueError:
        pass
    try:
        Path(os.path.realpath(candidate)).relative_to(Path(os.path.realpath(directory)))
        return True
    except ValueError:
        pass
    if os.path.lexists(directory):
        cursor = cand_path
        while True:
            if os.path.lexists(cursor):
                try:
                    if os.path.samefile(cursor, directory):
                        return True
                except OSError:
                    pass
            parent = cursor.parent
            if parent == cursor:
                break
            cursor = parent
    return False


def _arg_value(argv: tuple[str, ...], flag: str) -> str | None:
    for index, token in enumerate(argv):
        if token == flag and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _match_owned_connector_release(
    request: InstallRequest,
    binding: InstallationBinding,
    argv: tuple[str, ...],
) -> str:
    candidate_releases = [binding.active_release_id]
    if binding.previous_release_id and binding.previous_release_id != binding.active_release_id:
        candidate_releases.append(binding.previous_release_id)
    exe = _norm_path(argv[0])
    config_arg = _arg_value(argv, "--config")
    token_arg = _arg_value(argv, "--token-file")
    matched = any(
        exe == _norm_path(Path(request.app_dir) / "releases" / rid / "connector" / "cloudflared.exe")
        and config_arg is not None
        and _norm_path(config_arg) == _norm_path(Path(request.app_dir) / "releases" / rid / "connector" / "config.json")
        for rid in candidate_releases
    )
    if not matched or token_arg is None:
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared service does not belong to this verified installation",
        )
    return token_arg


def _verify_connector_state_ownership(
    state_path: Path,
    secret_root: Path,
    token_path: Path,
    binding: InstallationBinding,
) -> None:
    if not state_path.is_file():
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared ownership state.json is missing for this installation",
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared ownership state.json is unreadable",
        ) from exc
    if (
        not isinstance(state, dict)
        or state.get("install_id") != binding.install_id
        or state.get("dataset_id") != binding.dataset_id
        or type(state.get("expected_restore_epoch")) is not int
        or state.get("expected_restore_epoch") != binding.expected_restore_epoch
    ):
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared state.json does not belong to this installation",
        )
    generation = state.get("credential_generation")
    if type(generation) is not int or generation < 1:
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared state.json lacks a valid positive integer credential_generation",
        )
    if _norm_path(token_path) != _norm_path(secret_root / f"credential-g{generation}.token"):
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared credential generation does not match installation state",
        )


def _verify_owned_connector_service(
    request: InstallRequest,
    binding: InstallationBinding,
    observed_conn: object,
) -> None:
    argv = tuple(getattr(observed_conn, "argv", ()) or ())
    if not argv:
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared service has no observable command line",
        )
    token_arg = _match_owned_connector_release(request, binding, argv)
    connector_root = layout.machine_root(request) / "connectors" / "cloudflare"
    secret_root = connector_root / "secrets"
    state_path = connector_root / "state.json"
    token_path = Path(token_arg)
    for path in (connector_root, secret_root, state_path, token_path):
        reject_reparse_components(path)
    if (
        _norm_path(token_path.parent) != _norm_path(secret_root)
        or _CONNECTOR_TOKEN_FILE.fullmatch(token_path.name) is None
    ):
        raise LifecycleViolation(
            "uninstall_foreign_service_refused",
            "TicketboxCloudflared token file does not belong to this installation",
        )
    _verify_connector_state_ownership(state_path, secret_root, token_path, binding)


def verify_owned_services(
    runner: CommandRunner,
    observer: ScmObserver,
    request: InstallRequest,
    binding: InstallationBinding,
) -> None:
    for path in (
        Path(request.app_dir),
        Path(request.program_data_root),
        Path(binding.data_root),
        layout.machine_root(request),
    ):
        reject_reparse_components(path)

    if service_exists(runner, binding.backend_service_name):
        observed = observer.observe(binding.backend_service_name)
        expected = expected_backend_service(
            replace(request, target_release_id=binding.active_release_id),
            start_type=SERVICE_DEMAND_START,
        )
        try:
            require_service_configuration(
                binding.backend_service_name,
                observed,
                expected,
                allowed_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
            )
        except LifecycleError as exc:
            raise LifecycleViolation(
                "uninstall_foreign_service_refused",
                "TicketboxBackend service does not belong to this verified installation",
            ) from exc

    if service_exists(runner, binding.pg_service_name):
        observed_pg = observer.observe(binding.pg_service_name)
        expected_pg = expected_pg_service(request)
        try:
            require_service_configuration(
                binding.pg_service_name,
                observed_pg,
                expected_pg,
                allowed_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
            )
        except LifecycleError as exc:
            raise LifecycleViolation(
                "uninstall_foreign_service_refused",
                "TicketboxPg service does not belong to this verified installation",
            ) from exc

    if service_exists(runner, CONNECTOR_SERVICE_NAME):
        observed_conn = observer.observe(CONNECTOR_SERVICE_NAME)
        _verify_owned_connector_service(request, binding, observed_conn)


def _is_hex_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def _normalized_expected_manifests(
    binding: InstallationBinding,
    expected_manifests: Mapping[str, str] | None,
) -> dict[str, str]:
    manifest_shas = {
        rid.casefold(): sha.lower()
        for rid, sha in (expected_manifests or {}).items()
        if _is_hex_sha256(sha)
    }
    active_key = binding.active_release_id.casefold()
    if active_key not in manifest_shas and _is_hex_sha256(binding.release_manifest_sha256):
        manifest_shas[active_key] = binding.release_manifest_sha256.lower()
    return manifest_shas


def _verify_manifest_payload_target(
    rid: str,
    target: Path,
    record_path: object,
    expected_file_sha: str,
    *,
    resuming_cleanup: bool,
) -> None:
    if not os.path.lexists(target):
        if not resuming_cleanup:
            raise LifecycleViolation(
                "uninstall_release_file_missing",
                f"release {rid} payload file is missing before uninstall: {record_path}",
            )
        return
    if not target.is_file():
        raise LifecycleViolation(
            "uninstall_release_file_hash_mismatch",
            f"release {rid} payload entry is not a regular file: {record_path}",
        )
    if _sha256_file(target) != expected_file_sha:
        raise LifecycleViolation(
            "uninstall_release_file_hash_mismatch",
            f"release {rid} payload file digest does not match verified manifest: {record_path}",
        )


def _verify_expected_release_files(
    rid: str,
    app_dir: Path,
    release_dir: Path,
    manifest_path: Path,
    expected: Mapping[str, Mapping[str, object]],
    *,
    resuming_cleanup: bool,
) -> tuple[set[str], list[Path]]:
    release_prefix = f"releases/{rid.casefold()}/"
    expected_norm_paths: set[str] = {_norm_path(manifest_path)}
    payload_files: list[Path] = []
    for key, record in expected.items():
        if not key.startswith(release_prefix):
            continue
        target = app_dir / Path(str(record["path"]))
        reject_reparse_components(target)
        try:
            Path(os.path.abspath(target)).relative_to(Path(os.path.abspath(release_dir)))
        except ValueError as exc:
            raise LifecycleViolation(
                "uninstall_path_escaped",
                f"release manifest file escapes release directory: {record['path']}",
            ) from exc
        expected_file_sha = record.get("sha256")
        if not _is_hex_sha256(expected_file_sha):
            raise LifecycleViolation(
                "uninstall_release_file_hash_mismatch",
                f"release {rid} manifest lacks a valid SHA-256 digest for {record['path']}",
            )
        assert isinstance(expected_file_sha, str)
        expected_norm_paths.add(_norm_path(target))
        _verify_manifest_payload_target(
            rid,
            target,
            record["path"],
            expected_file_sha,
            resuming_cleanup=resuming_cleanup,
        )
        payload_files.append(target)
    return expected_norm_paths, payload_files


def _verify_release_dir_entries(
    rid: str,
    release_dir: Path,
    expected_norm_paths: set[str],
) -> None:
    for root_dir, dirs, files in os.walk(
        release_dir,
        topdown=True,
        followlinks=False,
        onerror=_raise_walk_error,
    ):
        root_path = Path(root_dir)
        reject_reparse_components(root_path)
        for dirname in dirs:
            reject_reparse_components(root_path / dirname)
        for filename in files:
            candidate = root_path / filename
            reject_reparse_components(candidate)
            if not candidate.is_file():
                raise LifecycleViolation(
                    "uninstall_release_unexpected_file",
                    f"release {rid} contains a non-regular file: {candidate.relative_to(release_dir)}",
                )
            if _norm_path(candidate) not in expected_norm_paths:
                raise LifecycleViolation(
                    "uninstall_release_unexpected_file",
                    f"release {rid} contains an unexpected file outside its verified manifest: "
                    f"{candidate.relative_to(release_dir)}",
                )


def _plan_single_release_cleanup(
    rid: str,
    *,
    app_dir: Path,
    releases_root: Path,
    binding: InstallationBinding,
    manifest_shas: Mapping[str, str],
    running_exe: str,
    resuming_cleanup: bool,
) -> tuple[str, Path, Path | None, list[Path]] | None:
    release_dir = releases_root / rid
    manifest_path = release_dir / "release-manifest.json"
    reject_reparse_components(release_dir)
    reject_reparse_components(manifest_path)
    is_active = rid.casefold() == binding.active_release_id.casefold()
    if not os.path.lexists(release_dir):
        if is_active and not resuming_cleanup:
            raise LifecycleViolation(
                "uninstall_release_manifest_missing",
                f"active release directory {rid} is missing; refusing uninstall cleanup",
            )
        return None
    if _is_path_inside_dir(running_exe, release_dir):
        raise LifecycleViolation(
            "uninstall_running_from_release_dir",
            f"controlled uninstall must execute from shared bin/lifecycle, not from release {rid}",
        )
    if resuming_cleanup and release_dir.is_dir() and not os.path.lexists(manifest_path):
        if not any(release_dir.iterdir()):
            return (rid, release_dir, None, [])
        raise LifecycleViolation(
            "uninstall_release_manifest_missing",
            f"release {rid} lacks release-manifest.json while non-empty; refusing blind deletion",
        )
    expected_sha = manifest_shas.get(rid.casefold())
    if expected_sha is None:
        raise LifecycleViolation(
            "uninstall_release_manifest_unverified",
            f"release {rid} lacks a verified manifest digest from installation history; refusing deletion",
        )
    if not manifest_path.is_file():
        raise LifecycleViolation(
            "uninstall_release_manifest_missing",
            f"release {rid} lacks release-manifest.json; refusing blind deletion",
        )
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest().lower() != expected_sha:
        raise LifecycleViolation(
            "uninstall_release_manifest_mismatch",
            f"release {rid} manifest digest does not match verified installation history",
        )
    manifest = _parse_manifest(manifest_bytes, rid)
    expected = _expected_files(manifest, app_dir, manifest_path)
    expected_norm_paths, payload_files = _verify_expected_release_files(
        rid,
        app_dir,
        release_dir,
        manifest_path,
        expected,
        resuming_cleanup=resuming_cleanup,
    )
    _verify_release_dir_entries(rid, release_dir, expected_norm_paths)
    return (rid, release_dir, manifest_path, payload_files)


def plan_registered_release_cleanup(
    request: InstallRequest,
    binding: InstallationBinding,
    *,
    release_ids: tuple[str, ...],
    expected_manifests: Mapping[str, str] | None = None,
    resuming_cleanup: bool = False,
) -> list[tuple[str, Path, Path | None, list[Path]]]:
    app_dir = Path(request.app_dir)
    releases_root = app_dir / "releases"
    reject_reparse_components(app_dir)
    reject_reparse_components(releases_root)
    manifest_shas = _normalized_expected_manifests(binding, expected_manifests)
    if os.path.lexists(releases_root) and not releases_root.is_dir():
        raise LifecycleViolation(
            "uninstall_release_manifest_missing",
            "releases path exists but is not a directory; refusing uninstall cleanup",
        )
    if not os.path.lexists(releases_root):
        if not resuming_cleanup and any(
            rid.casefold() == binding.active_release_id.casefold() for rid in release_ids
        ):
            raise LifecycleViolation(
                "uninstall_release_manifest_missing",
                "active release directory is missing; refusing blind uninstall cleanup",
            )
        return []
    registered_keys = {rid.casefold() for rid in release_ids}
    for entry in sorted(releases_root.iterdir(), key=lambda path: path.name.casefold()):
        reject_reparse_components(entry)
        if entry.name.casefold() not in registered_keys:
            raise LifecycleViolation(
                "uninstall_unregistered_release_present",
                f"unregistered entry {entry.name} exists under releases directory; refusing uninstall",
            )
    running_exe = sys.executable or ""
    planned: list[tuple[str, Path, Path | None, list[Path]]] = []
    for rid in release_ids:
        entry_plan = _plan_single_release_cleanup(
            rid,
            app_dir=app_dir,
            releases_root=releases_root,
            binding=binding,
            manifest_shas=manifest_shas,
            running_exe=running_exe,
            resuming_cleanup=resuming_cleanup,
        )
        if entry_plan is not None:
            planned.append(entry_plan)
    return planned
