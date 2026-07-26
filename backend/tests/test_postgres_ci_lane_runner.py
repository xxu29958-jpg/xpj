from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_postgres_pytest_lane
from scripts.run_postgres_pytest_lane import (
    POSTGRES_PYTEST_LANE_DEST,
    POSTGRES_PYTEST_SHARD_COUNT_DEST,
    POSTGRES_PYTEST_SHARD_INDEX_DEST,
    build_pytest_collection_command,
    build_pytest_command,
    nodeid_shard,
    validate_lane_collection,
    validate_shard_coordinates,
)
from tests._infra.postgres_sharding_plugin import pytest_collection_modifyitems

_ROOT = Path(__file__).resolve().parents[2]


class _DeselectRecorder:
    def __init__(self) -> None:
        self.items: tuple[object, ...] = ()

    def pytest_deselected(self, *, items: list[object]) -> None:
        self.items = tuple(items)


class _ShardConfig:
    def __init__(self, shard_index: int) -> None:
        self.hook = _DeselectRecorder()
        self._options = {
            POSTGRES_PYTEST_LANE_DEST: "ordinary",
            POSTGRES_PYTEST_SHARD_INDEX_DEST: shard_index,
            POSTGRES_PYTEST_SHARD_COUNT_DEST: 2,
        }

    def getoption(self, name: str) -> object:
        return self._options[name]


def _assert_generated_lane_commands() -> None:
    ordinary = build_pytest_command(
        lane="ordinary",
        workers=4,
        shard_index=1,
        shard_count=2,
    )
    assert ordinary[:3] == (sys.executable, "-m", "pytest")
    assert ordinary.count("tests") == 1
    assert ordinary[ordinary.index("--xpj-postgres-lane") + 1] == "ordinary"
    assert ordinary[ordinary.index("-m", 3) + 1] == "not real_db"
    assert ordinary[ordinary.index("-n") + 1] == "4"
    assert ordinary[ordinary.index("--dist") + 1] == "worksteal"
    assert "--max-worker-restart=0" in ordinary
    assert ordinary[ordinary.index("--xpj-postgres-shard-index") + 1] == "1"
    assert ordinary[ordinary.index("--xpj-postgres-shard-count") + 1] == "2"
    for forbidden in ("-k", "--ignore", "--ignore-glob", "--deselect"):
        assert forbidden not in ordinary

    ordinary_serial = build_pytest_command(lane="ordinary", workers=1)
    real_db = build_pytest_command(lane="real-db", workers=1)
    assert "-n" not in ordinary_serial
    assert real_db[real_db.index("-m", 3) + 1] == "real_db"
    assert real_db[real_db.index("--xpj-postgres-lane") + 1] == "real-db"
    assert real_db[real_db.index("--xpj-postgres-shard-index") + 1] == "0"
    assert real_db[real_db.index("--xpj-postgres-shard-count") + 1] == "1"
    assert "-n" not in real_db


def _assert_main_forwards_shard_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...],
        *,
        check: bool,
        env: dict[str, str],
        shell: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert env == {}
        assert shell is False
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    with monkeypatch.context() as patch:
        patch.setattr(run_postgres_pytest_lane, "child_environment", lambda source: {})
        patch.setattr(run_postgres_pytest_lane.subprocess, "run", fake_run)
        for shard_index in (0, 1):
            assert (
                run_postgres_pytest_lane.main(
                    (
                        "--lane",
                        "ordinary",
                        "--workers",
                        "4",
                        "--shard-index",
                        str(shard_index),
                        "--shard-count",
                        "2",
                    )
                )
                == 0
            )
    assert len(commands) == 2
    for shard_index, command in enumerate(commands):
        assert command[command.index("--xpj-postgres-shard-index") + 1] == str(
            shard_index
        )
        assert command[command.index("--xpj-postgres-shard-count") + 1] == "2"


def _assert_invalid_runner_coordinates_fail_closed() -> None:
    with pytest.raises(ValueError, match="serial"):
        build_pytest_command(lane="real-db", workers=2)
    with pytest.raises(ValueError, match="between 1 and 4"):
        build_pytest_command(lane="ordinary", workers=5)
    with pytest.raises(ValueError, match="only the ordinary"):
        build_pytest_command(
            lane="real-db",
            workers=1,
            shard_index=0,
            shard_count=2,
        )
    with pytest.raises(ValueError, match="outside"):
        build_pytest_command(
            lane="ordinary",
            workers=4,
            shard_index=2,
            shard_count=2,
        )


def _assert_nodeid_shards_form_an_exact_partition() -> None:
    nodeids = tuple(f"tests/test_example.py::test_case[{index}]" for index in range(64))
    assignments = {
        nodeid: nodeid_shard(nodeid, shard_count=2)
        for nodeid in nodeids
    }
    assert set(assignments) == set(nodeids)
    assert set(assignments.values()) == {0, 1}
    assert all(
        sum(nodeid_shard(nodeid, shard_count=2) == shard for shard in range(2))
        == 1
        for nodeid in nodeids
    )
    validate_shard_coordinates(lane=None, shard_index=0, shard_count=1)


def _hook_partition(shard_index: int) -> tuple[set[str], set[str]]:
    items = [
        SimpleNamespace(nodeid=f"tests/test_example.py::test_case[{index}]")
        for index in range(64)
    ]
    config = _ShardConfig(shard_index)
    pytest_collection_modifyitems(config, items)
    return (
        {str(item.nodeid) for item in items},
        {str(item.nodeid) for item in config.hook.items},
    )


def _assert_hook_forms_complementary_shards() -> None:
    selected_zero, deselected_zero = _hook_partition(0)
    selected_one, deselected_one = _hook_partition(1)
    expected = {
        f"tests/test_example.py::test_case[{index}]"
        for index in range(64)
    }
    assert selected_zero.isdisjoint(selected_one)
    assert selected_zero | selected_one == expected
    assert deselected_zero == selected_one
    assert deselected_one == selected_zero


def _assert_collection_contract_is_fail_closed() -> None:
    collection = build_pytest_collection_command("tests")
    assert collection[:4] == (sys.executable, "-m", "pytest", "tests")
    assert "--collect-only" in collection
    assert "--strict-markers" in collection
    assert collection[collection.index("-o") + 1] == "addopts="
    with pytest.raises(ValueError, match="explicit path"):
        build_pytest_collection_command("--ignore=tests")

    validate_lane_collection(lane=None, selected_real_db=[])
    validate_lane_collection(lane="ordinary", selected_real_db=[False, False])
    validate_lane_collection(lane="real-db", selected_real_db=[True, True])
    with pytest.raises(ValueError, match="selected no tests"):
        validate_lane_collection(lane="real-db", selected_real_db=[])
    with pytest.raises(ValueError, match="selected a real_db test"):
        validate_lane_collection(lane="ordinary", selected_real_db=[False, True])
    with pytest.raises(ValueError, match="selected an ordinary test"):
        validate_lane_collection(lane="real-db", selected_real_db=[True, False])


def _assert_local_verify_uses_postgres_authorities() -> None:
    script = (_ROOT / "scripts" / "verify_project.ps1").read_text(encoding="utf-8-sig")
    assert '"scripts.run_postgres_pytest_lane"' in script
    assert script.count('"-m",\n        "scripts.run_postgres_pytest_lane"') == 1
    assert script.count('"-m",\n            "scripts.run_postgres_pytest_lane"') == 1
    assert '"ordinary"' in script
    assert '"real-db"' in script
    assert '"scripts.write_test_postgres_env"' in script
    assert '"test_pg_storage_contract.ps1"' in script
    assert '"test_pg_auth_contract.ps1"' in script
    assert '"scripts\\release_audit.py"' in script
    assert '"scripts\\postgres_backup_drill.py"' in script
    assert '"-m", "pytest"' not in script
    assert "C:\\Program Files" not in script
    assert "GetFolderPath" in script


def _assert_root_conftest_registers_the_sharding_plugin() -> None:
    source = (_ROOT / "backend" / "tests" / "conftest.py").read_text(
        encoding="utf-8"
    )
    module = ast.parse(source)
    plugin_assignments = [
        statement.value
        for statement in module.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name) and target.id == "pytest_plugins"
    ]
    assert len(plugin_assignments) == 1
    assert ast.literal_eval(plugin_assignments[0]) == (
        "tests._infra.postgres_sharding_plugin",
    )


def test_postgres_lane_runner_is_the_single_pytest_command_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_generated_lane_commands()
    _assert_main_forwards_shard_coordinates(monkeypatch)
    _assert_invalid_runner_coordinates_fail_closed()
    _assert_nodeid_shards_form_an_exact_partition()
    _assert_hook_forms_complementary_shards()
    _assert_collection_contract_is_fail_closed()
    module_entry = subprocess.run(
        [sys.executable, "-m", "scripts.run_postgres_pytest_lane", "--help"],
        cwd=_ROOT / "backend",
        check=False,
        capture_output=True,
        text=True,
    )
    assert module_entry.returncode == 0, module_entry.stderr
    _assert_local_verify_uses_postgres_authorities()
    _assert_root_conftest_registers_the_sharding_plugin()
