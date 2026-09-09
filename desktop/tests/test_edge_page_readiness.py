"""Document startup must not consume the actual layout/interaction probe deadline."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _edge_cdp


def _browser(monkeypatch: pytest.MonkeyPatch, *, document_ready_at: float, probe_exists: bool):
    clock = SimpleNamespace(elapsed=0.0)

    def sleep(seconds):
        clock.elapsed += seconds

    class Page:
        def request(self, method, parameters):
            if method != "Runtime.evaluate":
                return {}
            clock.elapsed += 2.0
            if parameters["expression"] == "window.probe":
                if probe_exists and clock.elapsed >= document_ready_at:
                    return {"result": {"type": "string", "value": "ready"}}
                return {"result": {"type": "undefined"}}
            return {"result": {"type": "boolean", "value": clock.elapsed >= document_ready_at}}

    process = object()
    stopped = []
    monkeypatch.setattr(_edge_cdp, "time", SimpleNamespace(monotonic=lambda: clock.elapsed, sleep=sleep))
    monkeypatch.setattr(_edge_cdp.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(_edge_cdp, "_wait_for_devtools", lambda *_args: (9222, "/browser"))
    monkeypatch.setattr(_edge_cdp, "_page_websocket", lambda _port: "ws://127.0.0.1:9222/page")
    monkeypatch.setattr(_edge_cdp, "_WebSocket", lambda _endpoint: Page())
    monkeypatch.setattr(_edge_cdp, "_stop_edge", lambda child, **_kwargs: stopped.append(child))
    return clock, stopped, process


def test_delayed_document_still_runs_the_real_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _clock, stopped, process = _browser(monkeypatch, document_ready_at=16, probe_exists=True)
    result = _edge_cdp._evaluate_page_once("edge.exe", profile=tmp_path / "profile",
        url="file:///qualification.html", width=820, height=660, expression="window.probe")
    assert result == "ready"
    assert stopped == [process]


def test_ready_document_with_no_probe_still_fails_within_the_probe_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock, stopped, process = _browser(monkeypatch, document_ready_at=0, probe_exists=False)
    with pytest.raises(AssertionError, match="layout probe did not become available"):
        _edge_cdp._evaluate_page_once("edge.exe", profile=tmp_path / "profile",
            url="file:///qualification.html", width=820, height=660, expression="window.probe")
    assert clock.elapsed < 16
    assert stopped == [process]


def test_document_that_never_loads_fails_and_closes_the_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock, stopped, process = _browser(monkeypatch, document_ready_at=999, probe_exists=True)
    with pytest.raises(AssertionError, match="document did not become ready"):
        _edge_cdp._evaluate_page_once("edge.exe", profile=tmp_path / "profile",
            url="file:///qualification.html", width=820, height=660, expression="window.probe")
    assert clock.elapsed < 35
    assert stopped == [process]
