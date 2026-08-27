from __future__ import annotations

import json
from pathlib import Path

from ticketbox_lifecycle.cli import _emit_failure, main
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult


def test_cli_writes_failed_result_and_exits_nonzero(tmp_path: Path, capsys) -> None:
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
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "TicketboxLifecycle failed [bad_request_schema]: "
        "request schema is not ticketbox-lifecycle-request-v1\n"
    )


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


def test_failure_diagnostic_never_prints_a_pairing_code(capsys) -> None:
    password = "rA8dsfl29dkSla90_qwerty-Secret-Database-Value"
    _emit_failure(
        CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="install",
            operation_id="11111111-1111-4111-8111-111111111111",
            phase="failed_recoverable",
            code="owner_claim_failed",
            message=(
                "owner helper failed after producing 12345678\n"
                f"LINE 1: ALTER ROLE x PASSWORD '{password}'"
            ),
            installation_published=False,
        )
    )

    diagnostic = capsys.readouterr().err
    assert "owner_claim_failed" in diagnostic
    assert "12345678" not in diagnostic
    assert password not in diagnostic
    assert diagnostic.count("\n") == 1


def test_unhandled_failure_does_not_publish_exception_text(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from ticketbox_lifecycle import cli

    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    secret = "unexpected-secret-value-must-not-escape"
    request.write_text(
        '{"schema":"ticketbox-lifecycle-request-v1","operation_id":"op"}\n',
        encoding="utf-8",
    )

    def fail_parse(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "_parse_request", fail_parse)
    assert main(["install", "--request", str(request), "--result", str(result)]) == 2

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["code"] == "unhandled"
    assert secret not in payload["message"]
    assert secret not in capsys.readouterr().err
