from __future__ import annotations

from pathlib import Path

from ticketbox_lifecycle.schemas import InstallRequest

ACTIVE_OPERATION_TEMP_NAME = "active.json.pending.tmp"


def release_dir(request: InstallRequest) -> Path:
    return Path(request.app_dir) / "releases" / request.target_release_id


def pg_bin(request: InstallRequest) -> Path:
    return Path(request.app_dir) / "postgresql" / "bin"


def pgdata(request: InstallRequest) -> Path:
    return Path(request.data_root) / "pgdata"


def originals(request: InstallRequest) -> Path:
    return Path(request.data_root) / "attachments" / "originals"


def backend_logs(request: InstallRequest) -> Path:
    return Path(request.program_data_root) / "logs" / "backend"


def machine_root(request: InstallRequest) -> Path:
    return Path(request.program_data_root) / "machine"


def secrets_dir(request: InstallRequest) -> Path:
    return machine_root(request) / "secrets"


def pg_passfile(request: InstallRequest) -> Path:
    return secrets_dir(request) / "pgpass"


def postgres_pwfile(request: InstallRequest) -> Path:
    return secrets_dir(request) / "postgres.pwfile"


def postgres_password_file(request: InstallRequest) -> Path:
    return secrets_dir(request) / "postgres.password"


def migrator_password_file(request: InstallRequest) -> Path:
    return secrets_dir(request) / "ticketbox_migrator.password"


def runtime_password_file(request: InstallRequest) -> Path:
    return secrets_dir(request) / "ticketbox_runtime.password"


def shawl_exe(request: InstallRequest) -> Path:
    return Path(request.app_dir) / "bin" / "shawl.exe"


def backend_exe(request: InstallRequest) -> Path:
    return release_dir(request) / "backend" / "ticketbox-backend.exe"


def maintenance_helper(request: InstallRequest) -> Path:
    return release_dir(request) / "backend" / "ticketbox-database-maintenance.exe"


def active_operation(request: InstallRequest) -> Path:
    return machine_root(request) / "operations" / "active.json"


def tool(request: InstallRequest, name: str) -> Path:
    return pg_bin(request) / name
