"""Real Manager HTML consumer: local entry and durable-attempt continuation."""

from __future__ import annotations

import json
from pathlib import Path

from backend_manager.desktop_shell import discover_edge_executable
from tests._edge_cdp import evaluate_page
from tests.test_ui_browser_layout import _STARTUP_SCRIPT, _UI_HTML, _status


def test_local_first_use_and_original_code_continuation(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None
    status = {**_status(degraded=False), "product_available": True}
    script = (Path(__file__).parent / "fixtures" / "desktop_first_use_probe.js").read_text(encoding="utf-8")
    source = _UI_HTML.read_text(encoding="utf-8")
    assert source.count(_STARTUP_SCRIPT) == 1
    page = tmp_path / "first-use.html"
    page.write_text(source.replace(_STARTUP_SCRIPT, f"window.firstUseStatus = {json.dumps(status)};\n{script}"), encoding="utf-8")
    result = evaluate_page(
        edge, profile=tmp_path / "edge", url=page.as_uri(), width=390, height=844,
        expression="window.firstUseProbe",
    )
    assert result == {
        "localCodeReachable": True, "localCodeCommand": True,
        "deviceCodeReachableWithoutPhoneUrl": True,
        "dataAndIdentityExplained": True, "invalidCodeRetained": True,
        "invalidCanGetNewCode": True, "originalCodeRetained": True,
        "pendingExplained": True, "pendingCannotMintNewCode": True,
        "restartStillExplainsOriginalCode": True, "expiredCanGetNewCode": True,
        "pendingRebindExplained": True,
        "readFailureClosed": True, "unavailableClosed": True,
        "horizontalOverflow": False,
    }
