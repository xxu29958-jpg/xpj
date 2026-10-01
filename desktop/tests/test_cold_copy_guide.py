from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend_manager.desktop_shell import discover_edge_executable
from tests._edge_cdp import evaluate_page
from tests.test_ui_browser_layout import _render_probe_page, _status


@pytest.mark.skipif(os.name != "nt", reason="actual Windows Edge layout")
@pytest.mark.parametrize("width", [390, 1180])
def test_cold_copy_instructions_remain_readable_with_services_unavailable(tmp_path: Path, width: int) -> None:
    edge = discover_edge_executable()
    assert edge is not None
    script = f"render({json.dumps(_status(degraded=True))});" + """
    const guide = document.getElementById('coldCopyGuide');
    const summary = guide.querySelector('summary');
    summary.click();
    summary.focus();
    const commands = [...guide.querySelectorAll('pre')];
    document.body.dataset.coldProbe = JSON.stringify({
      open: guide.open,
      focused: document.activeElement === summary,
      targetHeight: summary.getBoundingClientRect().height,
      pageOverflow: document.documentElement.scrollWidth > innerWidth,
      clippedCommands: commands.some(p => p.scrollWidth > p.clientWidth + 1),
      visible: guide.getBoundingClientRect().height > summary.getBoundingClientRect().height,
      privilegedButtons: guide.querySelectorAll('button').length
    });
    """
    page = _render_probe_page(tmp_path, "cold-copy-guide.html", script)
    result = json.loads(evaluate_page(edge, profile=tmp_path / "edge", prepare_url=lambda _attempt: page.as_uri(),
                                     width=width, height=900, expression="document.body.dataset.coldProbe"))
    assert result["open"] and result["focused"] and result["visible"]
    assert result["targetHeight"] >= 44
    assert not result["pageOverflow"] and not result["clippedCommands"]
    assert result["privilegedButtons"] == 0
