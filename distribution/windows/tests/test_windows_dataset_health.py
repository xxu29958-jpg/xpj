from __future__ import annotations

import json
import urllib.request
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


class _HealthResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body

    def read1(self, size: int) -> bytes:
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _DirectOpener:
    def __init__(self, response: object) -> None:
        self._response = response

    def open(self, url: str, *, timeout: float):
        assert url.startswith("http://127.0.0.1:")
        assert timeout > 0
        return self._response


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


def _stub_direct_health(monkeypatch, response: object) -> None:
    def build_opener(handler):
        assert isinstance(handler, urllib.request.ProxyHandler)
        assert handler.proxies == {}
        return _DirectOpener(response)

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)


def _stub_json_health(monkeypatch, payload: object) -> None:
    _stub_direct_health(monkeypatch, _HealthResponse(json.dumps(payload).encode("utf-8")))


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


def test_health_ignores_ambient_proxy_and_accepts_exact_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    adapter = _adapter()

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
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


def test_health_rejects_oversized_response(tmp_path: Path, monkeypatch) -> None:
    request = _request(tmp_path)
    adapter = _adapter()
    payload = _health_payload(request)
    payload["padding"] = "x" * windows_dataset._HEALTH_BODY_LIMIT_BYTES
    _stub_json_health(monkeypatch, payload)
    monkeypatch.setattr(adapter, "_live_dataset_id", lambda _request: request.dataset_id)

    with pytest.raises(LifecycleError) as caught:
        adapter.verify(request, "health")

    assert caught.value.code == "health_identity_mismatch"
    assert caught.value.message == "installation health response is too large"


def test_health_rejects_slow_drip_response(tmp_path: Path, monkeypatch) -> None:
    request = _request(tmp_path)
    adapter = _adapter()

    class SlowResponse(_HealthResponse):
        def read(self) -> bytes:
            raise AssertionError("health must not use an unbounded read")

        def read1(self, size: int) -> bytes:
            del size
            clock.value += windows_dataset._HEALTH_TOTAL_TIMEOUT_SECONDS + 1
            return b"{"

    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

    clock = Clock()
    _stub_direct_health(monkeypatch, SlowResponse(b""))
    monkeypatch.setattr(windows_dataset, "time", clock)

    with pytest.raises(LifecycleError) as caught:
        adapter.verify(request, "health")

    assert caught.value.code == "health_unreachable"
    assert caught.value.message == "installation health response deadline elapsed"
