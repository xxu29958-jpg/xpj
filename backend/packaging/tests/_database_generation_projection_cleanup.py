import os
import shutil
import subprocess
import uuid
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1]


def ensure_projection_pg_stopped(pg_bin: Path, work_root: Path) -> str | None:
    data_dir = work_root / "pgdata"
    if not data_dir.is_dir():
        return None
    pg_ctl = pg_bin / "pg_ctl.exe"
    try:
        status = subprocess.run(
            [pg_ctl, "status", "-D", data_dir],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not inspect projection PostgreSQL at {data_dir}: {exc}"
    if status.returncode != 0:
        return None if status.returncode == 3 else f"unexpected pg_ctl status {status.returncode}"
    try:
        stopped = subprocess.run(
            [pg_ctl, "stop", "-D", data_dir, "-m", "immediate", "-w", "-t", "30"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        return f"timed out stopping projection PostgreSQL at {data_dir}"
    except OSError as exc:
        return f"could not stop projection PostgreSQL at {data_dir}: {exc}"
    try:
        final_status = subprocess.run(
            [pg_ctl, "status", "-D", data_dir],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not verify projection PostgreSQL cleanup at {data_dir}: {exc}"
    if stopped.returncode != 0 or final_status.returncode != 3:
        return (
            f"projection PostgreSQL remained live at {data_dir}: "
            f"stop={stopped.returncode}, status={final_status.returncode}"
        )
    return None


def projection_service_name(work_root: Path) -> str:
    prefix = "TicketboxProjectionTest-"
    suffix = work_root.name.removeprefix(prefix)
    assert work_root.name.startswith(prefix) and uuid.UUID(hex=suffix).hex == suffix
    return f"TicketboxProjection-{suffix}"


def ensure_projection_one_shot_service_absent(
    *, engine: str, service_name: str, shawl: Path, pg_bin: Path
) -> str | None:
    def literal(value: str | Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    command = f"""
$ErrorActionPreference = 'Stop'
. {literal(PACKAGING / "windows_installation_safety.ps1")}
. {literal(PACKAGING / "windows_database_safety.ps1")}
. {literal(PACKAGING / "windows_release_config.ps1")}
. {literal(PACKAGING / "windows_service_lifecycle.ps1")}
Remove-TicketboxOwnedServiceIfExists `
    -Name {literal(service_name)} `
    -ExpectedExecutable {literal(shawl)} `
    -TimeoutMilliseconds 60000 `
    -PollMilliseconds 100 `
    -ExpectedRuntimeExecutables @({literal(shawl)}, {literal(pg_bin / "postgres.exe")})
if (Test-TicketboxServiceExists {literal(service_name)}) {{
    throw 'projection one-shot service remained after cleanup'
}}
"""
    try:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=75,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not clean projection one-shot service {service_name}: {exc}"
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        return f"projection one-shot service cleanup failed for {service_name}: {detail}"
    return None


def projection_service_exists(*, engine: str, service_name: str) -> bool:
    literal_name = "'" + service_name.replace("'", "''") + "'"
    command = f"if (Get-Service -Name {literal_name} -ErrorAction SilentlyContinue) {{ exit 0 }}; exit 3"
    result = subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 3:
        return False
    raise RuntimeError(
        f"could not inspect projection one-shot service {service_name}: " + (result.stdout + result.stderr).strip()
    )


def remove_projection_machine_work_root(work_root: Path, *, host_cleanup_error: str | None) -> str | None:
    if host_cleanup_error is not None:
        return None
    program_data = Path(os.environ["PROGRAMDATA"])
    prefix = "TicketboxProjectionTest-"
    suffix = work_root.name.removeprefix(prefix)
    try:
        valid_suffix = uuid.UUID(hex=suffix).hex == suffix
    except ValueError:
        valid_suffix = False
    if work_root.parent != program_data or not work_root.name.startswith(prefix) or not valid_suffix:
        return f"refused to remove unexpected projection work root: {work_root}"
    try:
        shutil.rmtree(work_root)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"could not remove projection work root {work_root}: {exc}"
    if work_root.exists():
        return f"projection work root remained after cleanup: {work_root}"
    return None


def raise_projection_primary_failure(primary_failure: BaseException, cleanup_errors: tuple[str | None, ...]) -> None:
    for cleanup_error in cleanup_errors:
        if cleanup_error:
            primary_failure.add_note(cleanup_error)
    raise primary_failure


def cleanup_projection_runtime(
    *, engine: str, pg_bin: Path, shawl: Path, service_name: str, work_root: Path
) -> tuple[str | None, str | None, str | None]:
    def clean_service() -> str | None:
        error = ensure_projection_one_shot_service_absent(
            engine=engine, service_name=service_name, shawl=shawl, pg_bin=pg_bin
        )
        if error is not None:
            return error
        try:
            if projection_service_exists(engine=engine, service_name=service_name):
                return f"projection one-shot service remained after cleanup: {service_name}"
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            return f"could not verify projection one-shot service absence {service_name}: {exc}"
        return None

    try:
        service_was_present = projection_service_exists(engine=engine, service_name=service_name)
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        service_was_present = True
    if service_was_present:
        service_cleanup_error = clean_service()
        postgres_cleanup_error = ensure_projection_pg_stopped(pg_bin, work_root)
        if service_cleanup_error is not None:
            service_cleanup_error = clean_service()
    else:
        postgres_cleanup_error = ensure_projection_pg_stopped(pg_bin, work_root)
        service_cleanup_error = clean_service()
    if postgres_cleanup_error is not None and service_cleanup_error is None:
        postgres_cleanup_error = ensure_projection_pg_stopped(pg_bin, work_root)
    host_cleanup_error = "; ".join(error for error in (postgres_cleanup_error, service_cleanup_error) if error) or None
    root_cleanup_error = remove_projection_machine_work_root(work_root, host_cleanup_error=host_cleanup_error)
    return postgres_cleanup_error, service_cleanup_error, root_cleanup_error
