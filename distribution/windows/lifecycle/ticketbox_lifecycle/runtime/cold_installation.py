"""Read the existing installation authority while the administrator keeps it stopped."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import cold_archive, layout
from ticketbox_lifecycle.runtime.command import CommandRunner, SubprocessCommandRunner, sealed_postgres_env
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import scm_query_state
from ticketbox_lifecycle.runtime.windows_shipment import POSTGRES_MAJOR, WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallationBinding, InstallRequest


@dataclass
class ColdInstallation:
    stores: FilesystemStores
    runner: CommandRunner
    request: InstallRequest
    binding: InstallationBinding
    control_sha256: str
    allowed_operation_id: str | None = None
    excluded_prefixes: tuple[str, ...] = ()
    excluded_files: frozenset[str] = frozenset()

    @classmethod
    def read(
        cls,
        stores: FilesystemStores,
        app_dir: Path,
        program_data: Path,
        *,
        allowed_operation_id: str | None = None,
        target_release_id: str | None = None,
        runner: CommandRunner | None = None,
    ) -> ColdInstallation:
        binding = stores.read()
        if binding is None:
            raise LifecycleError("cold_installation_missing", "a verified installation is required")
        request = InstallRequest(
            schema=REQUEST_SCHEMA,
            command="inspect",
            operation_id=f"fresh-{binding.release_manifest_sha256}",
            request_hash=binding.release_manifest_sha256,
            target_release_id=binding.active_release_id,
            app_dir=str(app_dir),
            data_root=binding.data_root,
            program_data_root=str(program_data),
            pg_service_name=binding.pg_service_name,
            backend_service_name=binding.backend_service_name,
            pg_port=binding.pg_port,
            backend_port=binding.backend_port,
            postgres_major=binding.postgres_major,
            release_manifest_sha256=binding.release_manifest_sha256,
            install_id=binding.install_id,
            dataset_id=binding.dataset_id,
        )
        verifier = WindowsShipmentVerifier(app_dir, program_data)
        siblings = set(stores.known_sibling_releases(binding, exclude_release_id=binding.active_release_id))
        excluded_files: set[str] = set()
        if allowed_operation_id is not None:
            if target_release_id and target_release_id.casefold() != binding.active_release_id.casefold():
                siblings.add(target_release_id)
            excluded_files.update({
                "machine/operations/active.json",
                f"machine/operations/{layout.ACTIVE_OPERATION_TEMP_NAME}",
            })
        request = verifier.bind_and_verify(
            request,
            allowed_sibling_releases=frozenset(siblings),
        )
        excluded_prefixes = tuple(f"program/releases/{rid}/".casefold() for rid in sorted(siblings))
        control = layout.pgdata(request) / "global" / "pg_control"
        source = cls(
            stores,
            runner or SubprocessCommandRunner(),
            request,
            binding,
            _hash(control),
            allowed_operation_id=allowed_operation_id,
            excluded_prefixes=excluded_prefixes,
            excluded_files=frozenset(f.casefold() for f in excluded_files),
        )
        source.require_stopped()
        return source

    def exclude_entry(self, relative: str) -> bool:
        folded = relative.replace("\\", "/").casefold()
        if folded in self.excluded_files:
            return True
        return any(folded.startswith(prefix) for prefix in self.excluded_prefixes)

    def require_stopped(self) -> None:
        active = self.stores.read_active()
        if self.allowed_operation_id is None:
            if active is not None:
                raise LifecycleError("cold_installation_changed", "installation authority changed or is busy")
        elif (
            active is None
            or getattr(active, "kind", None) != "upgrade"
            or active.operation_id != self.allowed_operation_id
        ):
            raise LifecycleError("cold_installation_changed", "installation authority changed or is busy")
        if self.stores.read() != self.binding:
            raise LifecycleError("cold_installation_changed", "installation authority changed or is busy")
        for name in (self.binding.backend_service_name, self.binding.pg_service_name):
            if scm_query_state(self.runner, name) != "STOPPED":
                raise LifecycleError("cold_services_running", "both installed services must remain stopped")
        if _hash(layout.pgdata(self.request) / "global" / "pg_control") != self.control_sha256:
            raise LifecycleError("cold_cluster_changed", "PostgreSQL control state changed during cold copy")
        read_stopped_cluster(self.runner, layout.pg_bin(self.request), layout.pgdata(self.request))

    def roots(self) -> dict[str, Path]:
        data = Path(self.request.data_root)
        return {
            "program": Path(self.request.app_dir),
            "machine": layout.machine_root(self.request),
            "data/pgdata": data / "pgdata",
            "data/attachments": data / "attachments",
            "data/app": data / "app",
        }

    def identity(self) -> dict[str, object]:
        return {
            "install_id": self.binding.install_id,
            "dataset_id": self.binding.dataset_id,
            "restore_epoch": self.binding.expected_restore_epoch,
            "release_id": self.binding.active_release_id,
            "release_manifest_sha256": self.binding.release_manifest_sha256,
            "schema_revision": self.request.schema_revision,
            "postgres_major": self.binding.postgres_major,
            "postgres_system_identifier": read_stopped_cluster(
                self.runner, layout.pg_bin(self.request), layout.pgdata(self.request),
            ),
        }

    def recovery_point(self) -> dict[str, object]:
        return cold_archive.build_recovery_point(
            self.identity(),
            api_version="2026-10-11",
            semantic_revision=self.request.semantic_revision or "ticketbox-dataset-semantics-v1",
        )


def read_stopped_cluster(runner: SubprocessCommandRunner, pg_bin: Path, pgdata: Path) -> str:
    reject_reparse_components(pgdata / "global" / "pg_control")
    if (pgdata / "postmaster.pid").exists() or (pgdata / "PG_VERSION").read_text().strip() != str(POSTGRES_MAJOR):
        raise LifecycleError("cold_cluster_not_stopped", "the supported PostgreSQL cluster must be stopped")
    env = sealed_postgres_env()
    env["LC_ALL"] = "C"
    result = runner.run([str(pg_bin / "pg_controldata.exe"), "-D", str(pgdata)], env=env, timeout_s=30)
    fields = {key.strip(): value.strip() for line in result.stdout.splitlines() for key, sep, value in [line.partition(":")] if sep}
    identifier = fields.get("Database system identifier", "")
    if result.returncode or fields.get("Database cluster state") != "shut down" or not identifier.isdigit():
        raise LifecycleError("cold_cluster_not_stopped", "PostgreSQL must have completed a clean shutdown")
    return identifier


def _hash(path: Path) -> str:
    reject_reparse_components(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()
