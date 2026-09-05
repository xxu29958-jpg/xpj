"""Cheap regressions for the real Edge probe and its CDP result boundary."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import _edge_cdp


def _theme_probe() -> str:
    source = Path(__file__).with_name("test_web_bff_edge_e2e.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    assignment = next(
        statement for statement in module.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_THEME_PROBE" for target in statement.targets)
    )
    return ast.literal_eval(assignment.value)


@pytest.mark.parametrize("stage", ["no-root", "no-control", "loading", "ready"])
def test_real_theme_probe_waits_for_document_then_reports_actual_state(stage: str) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the dependency-free Edge probe contract"
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const {probe, stage} = JSON.parse(fs.readFileSync(0, "utf8"));
const button = {getAttribute: () => "true"};
const document = {
  readyState: stage === "loading" ? "loading" : "complete",
  documentElement: stage === "no-root" ? null : {getAttribute: () => "midnight"},
  querySelector: () => stage === "no-control" ? null : button,
  cookie: "ui_theme=midnight",
};
try {
  const value = vm.runInNewContext(probe, {
    document,
    localStorage: {getItem: () => "system"},
  });
  process.stdout.write(JSON.stringify(value === undefined ? {pending: true} : JSON.parse(value)));
} catch (error) {
  process.stdout.write(JSON.stringify({error: error.name}));
}
"""
    completed = subprocess.run(
        [node, "-e", script],
        input=json.dumps({"probe": _theme_probe(), "stage": stage}),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    expected = {"pending": True} if stage != "ready" else {
        "theme": "midnight",
        "storedTheme": "system",
        "cookie": "ui_theme=midnight",
        "systemPressed": "true",
    }
    assert json.loads(completed.stdout) == expected


def test_cdp_javascript_exception_is_not_returned_as_a_null_probe_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def request(self, method: str, _params: dict[str, object]) -> dict[str, object]:
            if method != "Runtime.evaluate":
                return {}
            return {
                "result": {"type": "object", "subtype": "error", "className": "TypeError"},
                "exceptionDetails": {"text": "Uncaught", "lineNumber": 3, "columnNumber": 18},
            }

    stopped: list[object] = []
    process = object()
    monkeypatch.setattr(_edge_cdp.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(_edge_cdp, "_wait_for_devtools", lambda *_args: (9222, "/browser"))
    monkeypatch.setattr(_edge_cdp, "_page_websocket", lambda _port: "ws://127.0.0.1:9222/page")
    monkeypatch.setattr(_edge_cdp, "_WebSocket", lambda _endpoint: Page())
    monkeypatch.setattr(_edge_cdp, "_stop_edge", lambda child, **_kwargs: stopped.append(child))

    with pytest.raises(AssertionError, match="layout probe raised a JavaScript exception"):
        _edge_cdp._evaluate_page_once(
            "edge.exe",
            profile=tmp_path / "profile",
            url="http://127.0.0.1/web",
            width=820,
            height=660,
            expression="document.documentElement.getAttribute('data-theme')",
        )
    assert stopped == [process]
