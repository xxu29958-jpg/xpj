from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_dataset
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter

from fakes import make_install_request


class _NoCommands:
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> CompletedCommand:
        del argv, env, timeout_s, input_text
        raise AssertionError("health contract test must not run a subprocess")


def _request(tmp_path: Path):
    return replace(
        make_install_request(tmp_path),
        install_id="11111111-1111-4111-8111-111111111111",
        dataset_id="22222222-2222-4222-8222-222222222222",
    )


def _adapter() -> WindowsDatasetAdapter:
    runner = _NoCommands()
    security = WindowsSecurityAdapter(runner, WindowsFileSecurity())
    return WindowsDatasetAdapter(runner, security)


def _health_payload(request) -> dict[str, object]:
    return {
        "contract": "ticketbox-installation-health-v2",
        "status": "ok",
        "backend_version": request.target_release_id,
        "installation_id": request.install_id,
        "runtime_access_state": "available",
        "owner_state": "configured",
    }


def _stub_health_body(monkeypatch, body: bytes) -> None:
    monkeypatch.setattr(
        windows_dataset,
        "fetch_installation_health",
        lambda _port: (200, body),
    )


def _stub_json_health(monkeypatch, payload: object) -> None:
    _stub_health_body(monkeypatch, json.dumps(payload).encode("utf-8"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend_version", "9.9.9"),
        ("installation_id", "22222222-2222-4222-8222-222222222222"),
        ("runtime_access_state", "repair_required"),
        ("owner_state", "recovery_required"),
    ],
)
def test_health_requires_exact_release_identity_and_usable_owner(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: str,
) -> None:
    request = _request(tmp_path)
    adapter = _adapter()
    payload = _health_payload(request)
    payload[field] = value

    _stub_json_health(monkeypatch, payload)
    monkeypatch.setattr(adapter, "_live_dataset_id", lambda _request: request.dataset_id)

    with pytest.raises(LifecycleError):
        adapter.verify(request, "health")


def test_health_accepts_exact_identity(tmp_path: Path, monkeypatch) -> None:
    request = _request(tmp_path)
    adapter = _adapter()

    _stub_json_health(monkeypatch, _health_payload(request))
    monkeypatch.setattr(adapter, "_live_dataset_id", lambda _request: request.dataset_id)

    adapter.verify(request, "health")


def test_health_rejects_non_object_json(tmp_path: Path, monkeypatch) -> None:
    request = _request(tmp_path)
    adapter = _adapter()
    _stub_json_health(monkeypatch, [])

    with pytest.raises(LifecycleError) as caught:
        adapter.verify(request, "health")

    assert caught.value.code == "health_identity_mismatch"


@pytest.mark.parametrize(
    "body",
    [
        b"1" * 5_000,
        b"[" * 1_200 + b"]" * 1_200,
    ],
    ids=("long_integer", "deep_array"),
)
def test_health_normalizes_bounded_json_parser_failures(
    tmp_path: Path,
    monkeypatch,
    body: bytes,
) -> None:
    request = _request(tmp_path)
    adapter = _adapter()
    _stub_health_body(monkeypatch, body)

    with pytest.raises(LifecycleError) as caught:
        adapter.verify(request, "health")

    assert caught.value.code == "health_identity_mismatch"
