from __future__ import annotations

import json
from pathlib import Path

from ticketbox_lifecycle.cli import main
from ticketbox_lifecycle.schemas import RESULT_SCHEMA


def test_cli_writes_failed_result_and_exits_nonzero(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    result = tmp_path / "operations" / "last-result.json"
    request.write_text('{"schema":"not-v1","operation_id":"11111111-1111-4111-8111-111111111111"}\n', encoding="utf-8")
    code = main(["install", "--request", str(request), "--result", str(result)])
    assert code == 2
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["phase"] == "failed_recoverable"
    assert payload["code"] == "bad_request_schema"
    assert payload["installation_published"] is False


def test_cli_overwrites_leftover_committed_result_before_work(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    result = tmp_path / "operations" / "last-result.json"
    result.parent.mkdir(parents=True)
    result.write_text(
        json.dumps(
            {
                "schema": RESULT_SCHEMA,
                "ok": True,
                "command": "install",
                "operation_id": "00000000-0000-4000-8000-000000000000",
                "phase": "committed",
                "code": "committed",
                "message": "fresh install committed",
                "installation_published": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    request.write_text(
        '{"schema":"not-v1","operation_id":"11111111-1111-4111-8111-111111111111"}\n',
        encoding="utf-8",
    )
    code = main(["install", "--request", str(request), "--result", str(result)])
    assert code == 2
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["phase"] != "committed"
    assert payload["operation_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["installation_published"] is False
