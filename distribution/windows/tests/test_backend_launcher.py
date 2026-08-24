from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ticketbox_backend_launcher.__main__ import launch_backend


def test_launcher_starts_active_release_with_data_dir(tmp_path: Path) -> None:
    app_dir = tmp_path / "Ticketbox"
    program_data = tmp_path / "ProgramData"
    data_root = program_data / "Ticketbox" / "data"
    backend_dir = app_dir / "releases" / "1.2.0" / "backend"
    backend_dir.mkdir(parents=True)
    backend = backend_dir / "ticketbox-backend.exe"
    backend.write_text("fake-backend", encoding="utf-8")
    machine = program_data / "Ticketbox" / "machine"
    machine.mkdir(parents=True)
    (machine / "secrets").mkdir()
    (machine / "secrets" / "backend.env").write_text(
        "DATABASE_URL=postgresql+psycopg://ticketbox_runtime:secret@127.0.0.1:5432/ticketbox\n",
        encoding="utf-8",
    )
    (machine / "installation.json").write_text(
        json.dumps(
            {
                "schema": "ticketbox-installed-instance-v1",
                "active_release_id": "1.2.0",
                "data_root": str(data_root),
                "backend_port": 8000,
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def runner(argv, env, check):
        del check
        seen["argv"] = list(argv)
        seen["env"] = dict(env)
        return SimpleNamespace(returncode=0)

    executable = app_dir / "bin" / "TicketboxBackendLauncher.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("launcher", encoding="utf-8")
    code = launch_backend(
        executable=executable,
        program_data=program_data,
        environ={"PATH": "C:\\Windows"},
        runner=runner,
    )
    assert code == 0
    assert seen["argv"] == [str(backend)]
    env = seen["env"]
    assert env["TICKETBOX_DATA_DIR"] == str(data_root / "app")
    assert env["TICKETBOX_OWNER_RECOVERY_CHANNEL"] == "managed_host"
    assert env["TICKETBOX_PORT"] == "8000"
    assert env["DATABASE_URL"].startswith("postgresql+psycopg://ticketbox_runtime:")
    assert not (data_root / "app" / ".env").exists()


def test_launcher_uses_unique_release_before_installation_json(tmp_path: Path) -> None:
    app_dir = tmp_path / "Ticketbox"
    program_data = tmp_path / "ProgramData"
    backend_dir = app_dir / "releases" / "1.2.0" / "backend"
    backend_dir.mkdir(parents=True)
    backend = backend_dir / "ticketbox-backend.exe"
    backend.write_text("fake-backend", encoding="utf-8")
    seen: dict[str, object] = {}

    def runner(argv, env, check):
        del check
        seen["argv"] = list(argv)
        seen["env"] = dict(env)
        return SimpleNamespace(returncode=0)

    executable = app_dir / "bin" / "TicketboxBackendLauncher.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("launcher", encoding="utf-8")
    code = launch_backend(
        executable=executable,
        program_data=program_data,
        environ={"PATH": "C:\\Windows"},
        runner=runner,
    )
    assert code == 0
    assert seen["argv"] == [str(backend)]
    env = seen["env"]
    assert env["TICKETBOX_DATA_DIR"] == str(program_data / "Ticketbox" / "data" / "app")
    assert env["TICKETBOX_PORT"] == "8000"
