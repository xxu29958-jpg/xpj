from __future__ import annotations

from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster
from ticketbox_lifecycle.runtime.command import CompletedCommand


@pytest.mark.parametrize("state", ["in production", "in crash recovery", "shut down in recovery", "shut down"])
def test_only_a_cleanly_stopped_complete_cluster_is_admitted(tmp_path: Path, state: str) -> None:
    (tmp_path / "PG_VERSION").write_text("17\n")

    class Runner:
        def run(self, argv, **kwargs):
            assert kwargs["env"]["LC_ALL"] == "C"
            assert Path(argv[0]).name == "pg_controldata.exe"
            return CompletedCommand(tuple(argv), 0, f"Database cluster state: {state}\nDatabase system identifier: 123456789\n", "")

    if state == "shut down":
        assert read_stopped_cluster(Runner(), tmp_path, tmp_path) == "123456789"
        (tmp_path / "postmaster.pid").write_text("123")
        with pytest.raises(LifecycleError, match="must be stopped"):
            read_stopped_cluster(Runner(), tmp_path, tmp_path)
    else:
        with pytest.raises(LifecycleError, match="clean shutdown"):
            read_stopped_cluster(Runner(), tmp_path, tmp_path)
