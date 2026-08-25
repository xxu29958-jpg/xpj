from __future__ import annotations

import subprocess

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner


def test_subprocess_timeout_has_a_typed_unknown_outcome(monkeypatch) -> None:
    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("initdb.exe", 180)

    monkeypatch.setattr(subprocess, "run", time_out)

    with pytest.raises(LifecycleError) as caught:
        SubprocessCommandRunner().run(["initdb.exe"], timeout_s=180)

    assert caught.value.code == "command_outcome_unknown"
    assert "180" in caught.value.message


def test_subprocess_start_failure_is_typed(monkeypatch) -> None:
    def fail_to_start(*_args, **_kwargs):
        raise FileNotFoundError("missing executable")

    monkeypatch.setattr(subprocess, "run", fail_to_start)

    with pytest.raises(LifecycleError) as caught:
        SubprocessCommandRunner().run(["missing.exe"])

    assert caught.value.code == "command_start_failed"
