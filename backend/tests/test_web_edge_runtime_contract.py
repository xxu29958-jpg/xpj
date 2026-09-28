"""Real Edge consumer gates for /web interactions and income-create draft refresh.

The income gate renders the actual production template on a synthetic origin;
it does not prove backend financial persistence or the complete draft lifecycle.
Skips cleanly on hosts without Microsoft Edge (CI lane that pins a real browser
runs it for real).
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import shutil
import sys
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlsplit

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BULK_BAR_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "bulk-bar.js"
_BULK_BAR_FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "bulk_bar_announcement_contract.html"
_BULK_EMPTY_RELOAD_FIXTURE = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "bulk_bar_empty_reload_contract.html"
)
_DRAWER_BULK_OCC_FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "drawer_bulk_occ_contract.html"
_DRAWER_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "drawer.js"
_REVIEW_KEYBOARD_FIXTURE = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "review_keyboard_contract.html"
)
_REVIEW_KEYBOARD_JS = (
    _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "review-keyboard.js"
)
_SHELL_KEYBOARD_FIXTURE = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "shell_keyboard_contract.html"
)
_SHELL_KEYBOARD_JS = (
    _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "shell-keyboard.js"
)
_EDGE_CDP: ModuleType | None = None


def test_income_create_original_form_draft_survives_refresh_in_real_edge(tmp_path: Path) -> None:
    """Real template consumer only; financial creation is a separate PostgreSQL gate."""
    edge = _discover_edge()
    templates = _REPO_ROOT / "backend/app/templates/web"
    static = (_REPO_ROOT / "backend/app/static").resolve()
    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
                        '{% block page_scripts %}{% endblock %}</head><body>'
                        '{% block content %}{% endblock %}</body></html>'}),
            FileSystemLoader(templates),
        ]),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.get_template("income_plans.html")
    scope = {"datasetId": "income-dataset", "clientGeneration": "income-generation",
             "accountId": "income-account", "ledgerId": "income-ledger", "deviceId": "income-device"}
    requests: list[dict[str, str]] = []
    posts: list[dict[str, str]] = []
    missing_resources: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def reply(self, body: bytes, *, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                self.reply(b'<!doctype html><html><head><meta charset="utf-8"></head><body>'
                           b'<script src="/probe.js"></script></body></html>')
                return
            if path == "/web/income-plans":
                refreshed = bool(requests)
                currency, month, key = ("CNY", "2026-10", "aa740c64-6e8d-45e8-80fd-5dd26a2f7126") if refreshed else (
                    "JPY", "2026-09", "19793a9e-7861-4c02-ae44-1cb35c5a1cdd")
                requests.append({"currency": currency, "month": month, "key": key})
                draft = {"home_currency_code": currency, "intent_month": month, "idempotency_key": key,
                         "label": "", "source_type": "salary", "frequency": "one_time", "amount_yuan": "",
                         "pay_day": "10", "income_month": "", "income_month_year": "2026",
                         "income_month_number": "10" if refreshed else "9"}
                body = template.render(
                    can_write=True, plans_active=[], plans_archived=[], selected_ledger_id=scope["ledgerId"],
                    income_draft_scope=scope, income_form_draft=draft, income_form_error=None,
                    income_form_review=False, income_year_options=[2025, 2026, 2027, 2028],
                    income_default_year="2026", income_default_month=draft["income_month_number"],
                    income_form_currency={"amount_placeholder": "0.00" if refreshed else "0",
                                          "inputmode": "decimal" if refreshed else "numeric"},
                    home_currency_code=currency, home_currency_symbol="¥", intent_month=month,
                    total_yuan="0", scheduled_yuan="0", reference_rates=[], missing_currency_codes=[],
                    message=None, error=None, asset_version="income-draft-contract",
                    csrf_field='<input type="hidden" name="csrf_token" value="synthetic-not-a-credential">',
                )
                self.reply(body.encode("utf-8"))
                return
            if path == "/probe.js":
                self.reply((_REPO_ROOT / "backend/tests/fixtures/income_create_draft_refresh_probe.js").read_bytes(),
                           content_type="text/javascript")
                return
            if path.startswith("/static/"):
                resource = (static / path.removeprefix("/static/")).resolve()
                if resource.is_relative_to(static) and resource.is_file():
                    self.reply(resource.read_bytes(), content_type="text/javascript")
                    return
                missing_resources.append(path)
            self.reply(b"not found", status=404)

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/web/income-plans/create":
                self.reply(b"not found", status=404)
                return
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("multipart/form-data"):
                message = BytesParser(policy=policy.default).parsebytes(
                    f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
                fields = {part.get_param("name", header="content-disposition"):
                          part.get_payload(decode=True).decode("utf-8") for part in message.iter_parts()}
            else:
                fields = {name: values[0] for name, values in parse_qs(raw.decode(), keep_blank_values=True).items()}
            posts.append(fields)
            if len(posts) == 1:
                # Synthetic unavailable response: no ACK and no financial database claim.
                self.reply(json.dumps({"message": "synthetic unknown result"}).encode(),
                           content_type="application/json", status=503)
                return
            self.reply(json.dumps({
                "ack": {"scope": scope, "clientRef": fields["idempotency_key"]},
                "receipt": {"public_id": "synthetic-income-receipt"},
                "next": "/web/income-plans?ledger_id=income-ledger",
            }).encode(), content_type="application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def prepare_url(_attempt: int) -> str:
        requests.clear()
        posts.clear()
        missing_resources.clear()
        return f"http://127.0.0.1:{server.server_port}/"

    try:
        probe = _edge_cdp().evaluate_page(
            edge, profile=tmp_path / "edge-income-create-draft-refresh", prepare_url=prepare_url,
            width=1024, height=768, expression="window.__incomeDraftRefreshProbe || undefined",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert missing_resources == [], f"actual template script failed to load: {missing_resources}"
    assert isinstance(probe, dict)
    assert probe.get("error") is None, probe
    assert requests[:2] == [
        {"currency": "JPY", "month": "2026-09", "key": "19793a9e-7861-4c02-ae44-1cb35c5a1cdd"},
        {"currency": "CNY", "month": "2026-10", "key": "aa740c64-6e8d-45e8-80fd-5dd26a2f7126"},
    ]
    expected = {"label": "九月接单收入草稿", "amount_yuan": " 001200 ", "source_type": "freelance",
                "frequency": "monthly", "pay_day": "23", "income_month_year": "2026", "income_month_number": "9",
                "intent_month": "2026-09", "home_currency_code": "JPY", "idempotency_key": "19793a9e-7861-4c02-ae44-1cb35c5a1cdd"}
    assert probe["before"]["fields"] == expected, probe
    assert probe["after"]["fields"] == expected, f"refresh replaced unsent original income draft: {probe}"
    assert probe["after"]["hash"] == probe["before"]["hash"], probe
    assert probe["after"]["navigationType"] == "reload", probe
    assert probe["after"]["amountLabel"] == "预计金额（JPY）", probe
    assert probe["after"]["amountPlaceholder"] == "0", probe
    assert probe["after"]["amountInputmode"] == "numeric", probe
    assert "2026-09" in probe["after"]["intentNotice"], probe
    assert "2026-10" not in probe["after"]["intentNotice"], probe
    submitted = {**expected, "amount_yuan": "1200"}
    assert probe["unknown"]["fields"] == submitted, probe
    assert probe["unknown"]["frozen"] is True, probe
    assert probe["unknown"]["record"]["clientRef"] == expected["idempotency_key"], probe
    assert probe["unknown"]["record"]["phase"] == "blocked", probe
    assert probe["duplicate"]["submitDisabled"] is True, probe
    assert probe["duplicate"]["record"] == probe["unknown"]["record"], probe
    assert probe["completed"] == {"originalRemoved": True, "newFormAvailable": True,
                                  "newKey": "aa740c64-6e8d-45e8-80fd-5dd26a2f7126",
                                  "location": "/web/income-plans?ledger_id=income-ledger", "hash": ""}, probe
    assert requests[2:] == [
        {"currency": "CNY", "month": "2026-10", "key": "aa740c64-6e8d-45e8-80fd-5dd26a2f7126"},
        {"currency": "CNY", "month": "2026-10", "key": "aa740c64-6e8d-45e8-80fd-5dd26a2f7126"},
    ], requests
    assert len(posts) == 2, posts
    assert posts[0] == posts[1], posts
    for name, value in submitted.items():
        assert posts[0][name] == value, posts
    assert posts[0]["ledger_id"] == scope["ledgerId"], posts
    assert json.loads(posts[0]["draft_scope"]) == scope, posts


def test_drawer_fx_status_and_retry_keep_draft_until_explicit_load_in_real_edge(tmp_path: Path) -> None:
    fixture = _REPO_ROOT / "backend/tests/fixtures/drawer_fx_original_form_contract.html"
    page = _write_fixture(tmp_path, fixture.name, fixture.read_text(encoding="utf-8").replace(
        "__DRAWER_URI__", html.escape(_DRAWER_JS.as_uri(), quote=True)))
    value = _evaluate_fixture(tmp_path, page=page, width=1024, height=768, profile_name="edge-drawer-fx-form")
    assert value == {
        "posts": [{"url": f"/web/expenses/1/{action}", "version": "11", "key": "original-key",
            "merchant": "Unsent merchant"} for action in ("fx-status", "fx")],
        "retained": {"reads": 1, "version": "11", "key": "original-key", "merchant": "Unsent merchant", "rowVersion": "11"},
        "loaded": {"reads": 2, "version": "12", "merchant": "Saved merchant", "rowVersion": "12"},
    }


def _discover_edge() -> str:
    if sys.platform != "win32":
        pytest.skip("real Web consumer gate requires Windows Microsoft Edge")

    candidates = [shutil.which("msedge")]
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("real Web consumer gate requires Microsoft Edge")


def _edge_cdp() -> ModuleType:
    """Reuse only Desktop's dependency-free Edge transport, not its product fixture."""
    global _EDGE_CDP
    if _EDGE_CDP is not None:
        return _EDGE_CDP
    module_path = _REPO_ROOT / "desktop" / "tests" / "_edge_cdp.py"
    spec = importlib.util.spec_from_file_location("_ticketbox_shared_edge_cdp", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _EDGE_CDP = module
    return module


def _write_fixture(tmp_path: Path, name: str, body: str) -> Path:
    page = tmp_path / name
    page.write_text("<!doctype html>\n" + body, encoding="utf-8")
    return page


def _evaluate_fixture(
    tmp_path: Path,
    *,
    page: Path,
    width: int,
    height: int,
    profile_name: str,
) -> dict[str, object]:
    value = _edge_cdp().evaluate_page(
        _discover_edge(),
        profile=tmp_path / profile_name,
        prepare_url=lambda _attempt: page.as_uri(),
        width=width,
        height=height,
        expression="window.__webConsumerProbe || undefined",
    )
    assert isinstance(value, dict)
    return value


def _assert_bulk_queue_exhaustion_reloads_authoritative_page(tmp_path: Path) -> None:
    page = _write_fixture(
        tmp_path,
        "bulk-bar-empty-reload-contract.html",
        _BULK_EMPTY_RELOAD_FIXTURE.read_text(encoding="utf-8").replace(
            "__BULK_BAR_URI__",
            html.escape(_BULK_BAR_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-bulk-bar-empty-reload-contract",
    )
    assert probe == {
        "authoritativeReloaded": True,
        "navigationType": "reload",
    }


def _assert_review_keyboard_behaves_in_real_edge(tmp_path: Path) -> None:
    page = _write_fixture(
        tmp_path,
        "review-keyboard-contract.html",
        _REVIEW_KEYBOARD_FIXTURE.read_text(encoding="utf-8").replace(
            "__REVIEW_KEYBOARD_URI__",
            html.escape(_REVIEW_KEYBOARD_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-review-keyboard-contract",
    )
    assert probe == {
        "down": {"active": "row-3", "prevented": True},
        "up": {"active": "row-1", "prevented": True},
        "end": {"active": "row-3", "prevented": True},
        "home": {"active": "row-1", "prevented": True},
        "j": {"active": "row-1", "prevented": False},
        "k": {"active": "row-1", "prevented": False},
        "composing": {"active": "row-1", "prevented": False},
        "inputArrow": {"active": "editor", "prevented": False},
        "drawerArrow": {"active": "row-1", "prevented": False},
        "confirm": {"active": "row-1", "prevented": True},
        "confirmCalls": 1,
    }


def test_shell_shortcuts_preserve_typing_and_permission_boundaries_in_real_edge(
    tmp_path: Path,
) -> None:
    page = _write_fixture(
        tmp_path,
        "shell-keyboard-contract.html",
        _SHELL_KEYBOARD_FIXTURE.read_text(encoding="utf-8").replace(
            "__SHELL_KEYBOARD_URI__",
            html.escape(_SHELL_KEYBOARD_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-shell-keyboard-contract",
    )

    assert probe == {
        "search": True,
        "manualExpense": True,
        "capture": True,
        "modified": False,
        "composing": False,
        "input": False,
        "drawer": False,
        "absent": False,
        "absentManualExpense": False,
        "clicks": {"search": 1, "manualExpense": 1, "capture": 1},
    }


def test_bulk_async_feedback_has_announcement_semantics_in_real_edge(
    tmp_path: Path,
) -> None:
    page = _write_fixture(
        tmp_path,
        "bulk-bar-announcement-contract.html",
        _BULK_BAR_FIXTURE.read_text(encoding="utf-8").replace(
            "__BULK_BAR_URI__",
            html.escape(_BULK_BAR_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-bulk-bar-announcement-contract",
    )

    assert probe["beforeEnhancement"] == {
        "checkAllHidden": True,
        "enhanced": False,
    }
    batch_mode = probe["batchMode"]
    assert batch_mode == {
        "enhanced": True,
        "checkAllHidden": False,
        "ariaDisabled": None,
        "tabIndex": None,
        "ariaCurrent": "true",
        "checkboxChecked": True,
        "checkboxTabIndex": 0,
        "navigationPrevented": False,
        "locationHash": "#row-1-navigation",
    }

    cleared = probe["cleared"]
    assert cleared == {
        "ariaDisabled": None,
        "hasTabIndex": False,
        "ariaCurrent": "true",
        "checkboxChecked": False,
        "activeElement": "check-1",
        "clearButtonType": "button",
        "formActive": False,
    }

    success = probe["successWithUndo"]
    assert success["role"] == "status"
    assert success["live"] == "polite"
    assert success["atomic"] == "true"
    assert "已确认 1 条流水。" in success["message"]
    assert success["undoLabel"] == "撤销刚才的批量操作"
    assert success["undoButtonLabel"] == "撤销刚才处理的 1 条流水"

    failure = probe["failure"]
    assert failure["role"] == "alert"
    assert failure["live"] == "assertive"
    assert failure["atomic"] == "true"
    assert failure["message"] == "批量操作失败，请重试。"
    _assert_bulk_queue_exhaustion_reloads_authoritative_page(tmp_path)


def test_drawer_save_resynchronizes_selected_row_occ_consumers_in_real_edge(
    tmp_path: Path,
) -> None:
    page = _write_fixture(
        tmp_path,
        "drawer-bulk-occ-contract.html",
        _DRAWER_BULK_OCC_FIXTURE.read_text(encoding="utf-8")
        .replace(
            "__BULK_BAR_URI__",
            html.escape(_BULK_BAR_JS.as_uri(), quote=True),
        )
        .replace(
            "__DRAWER_URI__",
            html.escape(_DRAWER_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-drawer-bulk-occ-contract",
    )

    assert probe == {
        "drawerOpenedWhileSelected": True,
        "checkboxChecked": True,
        "checkboxDataRowVersion": "12",
        "checkboxValue": "1:12",
        "quickConfirmSnapshot": "1:12",
        "bulkTokens": ["12"],
        "selectedCount": "1",
    }
    _assert_review_keyboard_behaves_in_real_edge(tmp_path)
