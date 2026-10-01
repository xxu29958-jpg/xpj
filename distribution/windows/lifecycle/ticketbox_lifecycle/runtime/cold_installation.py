"""Read the existing installation authority while the administrator keeps it stopped."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner, sealed_postgres_env
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import scm_query_state
from ticketbox_lifecycle.runtime.windows_shipment import POSTGRES_MAJOR, WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallationBinding, InstallRequest


@dataclass
class ColdInstallation:
    stores: FilesystemStores
    runner: SubprocessCommandRunner
    request: InstallRequest
    binding: InstallationBinding
    control_sha256: str

    @classmethod
    def read(cls, stores: FilesystemStores, app_dir: Path, program_data: Path) -> ColdInstallation:
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
        request = WindowsShipmentVerifier(app_dir, program_data).bind_and_verify(request)
        control = layout.pgdata(request) / "global" / "pg_control"
        source = cls(stores, SubprocessCommandRunner(), request, binding, _hash(control))
        source.require_stopped()
        return source

    def require_stopped(self) -> None:
        if self.stores.read_active() is not None or self.stores.read() != self.binding:
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
