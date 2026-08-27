from __future__ import annotations

from types import SimpleNamespace

import pytest
from fakes import make_install_request
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_dataset, windows_postgres, windows_scm
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_postgres import WindowsPostgresAdapter
from ticketbox_lifecycle.runtime.windows_scm import WindowsScmAdapter


class _NoCommands:
    def run(self, *_args, **_kwargs):
        raise AssertionError("deadline tests isolate external commands")


def _wall_clock_must_not_be_read() -> float:
    raise AssertionError("an elapsed-time budget read the adjustable wall clock")


def _bounded_ticks():
    ticks = iter((100.0, 100.0, 1000.0))
    return lambda: next(ticks)


def _transient(code: str):
    def fail(*_args, **_kwargs):
        raise LifecycleError(code, "not ready yet")

    return fail


def test_dataset_health_budget_ignores_wall_clock_changes(tmp_path, monkeypatch) -> None:
    adapter = WindowsDatasetAdapter(_NoCommands(), SimpleNamespace())
    monkeypatch.setattr(adapter, "_probe", _transient("health_unreachable"))
    monkeypatch.setattr(windows_dataset.time, "time", _wall_clock_must_not_be_read)
    monkeypatch.setattr(windows_dataset.time, "monotonic", _bounded_ticks())
    monkeypatch.setattr(windows_dataset.time, "sleep", lambda _seconds: None)

    with pytest.raises(LifecycleError) as caught:
        adapter.apply(make_install_request(tmp_path), "health")

    assert caught.value.code == "health_unreachable"


def test_postgres_start_budget_ignores_wall_clock_changes(tmp_path, monkeypatch) -> None:
    adapter = WindowsPostgresAdapter(_NoCommands(), SimpleNamespace())
    monkeypatch.setattr(adapter, "_require_ready", _transient("postgres_not_ready"))
    monkeypatch.setattr(windows_postgres, "start_service", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(windows_postgres, "scm_query_state", lambda *_args: "RUNNING")
    monkeypatch.setattr(windows_postgres.time, "time", _wall_clock_must_not_be_read)
    monkeypatch.setattr(windows_postgres.time, "monotonic", _bounded_ticks())
    monkeypatch.setattr(windows_postgres.time, "sleep", lambda _seconds: None)

    with pytest.raises(LifecycleError) as caught:
        adapter._start(make_install_request(tmp_path))

    assert caught.value.code == "postgres_not_ready"


def test_backend_start_budget_ignores_wall_clock_changes(tmp_path, monkeypatch) -> None:
    adapter = WindowsScmAdapter(_NoCommands(), SimpleNamespace(), SimpleNamespace())
    monkeypatch.setattr(windows_scm, "start_service", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(windows_scm, "service_running", lambda *_args: False)
    monkeypatch.setattr(windows_scm.time, "time", _wall_clock_must_not_be_read)
    monkeypatch.setattr(windows_scm.time, "monotonic", _bounded_ticks())
    monkeypatch.setattr(windows_scm.time, "sleep", lambda _seconds: None)

    with pytest.raises(LifecycleError) as caught:
        adapter._start_backend(make_install_request(tmp_path))

    assert caught.value.code == "backend_not_running"
