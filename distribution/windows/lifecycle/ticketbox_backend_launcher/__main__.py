"""Stable Ticketbox backend service launcher.

Shawl wraps this EXE, not a release-specific backend. The launcher reads
installation.json and execs releases/<active_release_id>/backend/ticketbox-backend.exe
with TICKETBOX_DATA_DIR bound to the published data root.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

_INSTALLATION_SCHEMA = "ticketbox-installed-instance-v1"


def app_dir_from_executable(executable: Path) -> Path:
    return executable.resolve().parent.parent


def binding_path(program_data: Path) -> Path:
    return program_data / "Ticketbox" / "machine" / "installation.json"


def load_binding(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != _INSTALLATION_SCHEMA:
        raise RuntimeError("installation.json schema is not ticketbox-installed-instance-v1")
    required = ("active_release_id", "data_root")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise RuntimeError("installation.json is missing " + ", ".join(missing))
    return payload


def backend_exe(app_dir: Path, release_id: str) -> Path:
    return app_dir / "releases" / str(release_id) / "backend" / "ticketbox-backend.exe"


def resolve_launch_plan(app_dir: Path, program_data: Path) -> dict[str, object]:
    path = binding_path(program_data)
    if path.is_file():
        return load_binding(path)
    releases = sorted(item for item in (app_dir / "releases").iterdir() if item.is_dir())
    if len(releases) != 1:
        raise RuntimeError("installation.json is absent and the installed release set is not unique")
    return {
        "active_release_id": releases[0].name,
        "data_root": str(program_data / "Ticketbox" / "data"),
        "backend_port": 8000,
    }


def launch_backend(
    *,
    executable: Path,
    program_data: Path,
    environ: Mapping[str, str],
    runner: Callable[..., object] | None = None,
) -> int:
    app_dir = app_dir_from_executable(executable)
    binding = resolve_launch_plan(app_dir, program_data)
    target = backend_exe(app_dir, str(binding["active_release_id"]))
    if not target.is_file():
        raise RuntimeError(f"active backend is missing: {target}")
    data_dir = Path(str(binding["data_root"])) / "app"
    data_dir.mkdir(parents=True, exist_ok=True)
    env_file = data_dir / ".env"
    secret_env = program_data / "Ticketbox" / "machine" / "secrets" / "backend.env"
    if not env_file.is_file() and secret_env.is_file():
        env_file.write_bytes(secret_env.read_bytes())
    child_env = dict(environ)
    child_env["TICKETBOX_DATA_DIR"] = str(data_dir)
    child_env.setdefault("TICKETBOX_OWNER_RECOVERY_CHANNEL", "managed_host")
    child_env["TICKETBOX_PORT"] = str(int(binding.get("backend_port") or 8000))
    invoke = runner or subprocess.run
    completed = invoke([str(target)], env=child_env, check=False)
    return int(getattr(completed, "returncode", 0))


def main(argv: list[str] | None = None) -> int:
    del argv
    program_data = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    return launch_backend(
        executable=Path(sys.executable if getattr(sys, "frozen", False) else __file__),
        program_data=program_data,
        environ=dict(os.environ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
