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


def test_accounting_time_subseconds_survive_the_actual_browser_control(tmp_path: Path) -> None:
    template = Environment(loader=FileSystemLoader(_REPO_ROOT / "backend/app/templates/web"),
        autoescape=select_autoescape(["html"])).get_template("_accounting_time_fields.html")
    walls = ["2026-11-01T01:30:15", "2026-11-01T01:30:15.123000", "2026-11-01T01:30:15.123456"]
    forms = []
    for index, wall in enumerate(walls):
        values = {"wall_time": wall, "wall_input_type": "datetime-local" if index == 0 else "text",
            "time_precision": "instant", "source_timezone": "America/New_York", "source_utc_offset_seconds": "-18000",
            "calendar_revision": "1", "user_local_date": "2026-11-01", "accounting_date": "", "offset_options": []}
        forms.append('<form>' + template.render(time_form=values,
            time_prefix=f"exact-{index}", time_name="expense_time", time_disabled=False) + '</form>')
    page = _write_fixture(tmp_path, "exact-time.html", '<meta charset="utf-8">' + ''.join(forms) +
        '<script>window.__webConsumerProbe={forms:Array.from(document.forms,'
        'form=>Object.fromEntries(new FormData(form).entries()))};</script>')
    probe = _evaluate_fixture(tmp_path, page=page, width=390, height=960, profile_name="edge-exact-time")
    for wall, values in zip(walls, probe["forms"], strict=True):
        assert values["expense_time"] == wall, "The real browser discarded a known instant before any user edit"
        assert values["source_utc_offset_seconds"] == "-18000" and values["calendar_revision"] == "1"


@pytest.mark.parametrize("raw", ["2026-11-01T01:30:15.123456", "2026-11-01 01:30:15"])
def test_manual_original_time_survives_real_draft_restoration(tmp_path: Path, raw: str) -> None:
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "ledger", "deviceId": "device"}
    time_values = {"time_precision": "instant", "calendar_revision": "1", "user_local_date": "2026-11-01",
        "source_timezone": "America/New_York", "source_utc_offset_seconds": "-18000", "accounting_date": ""}
    original = dict(amount_major="100.00", currency_code="CNY", home_currency_code="CNY", merchant="原提交商家",
        category="其他", spent_at=raw, note="原填写", return_to="", return_month="", return_recurring_public_id="",
        return_payment_expense_id="", **time_values)
    ref = "a" * 32
    record = {"version": 1, "scope": scope, "clientRef": ref, "phase": "submitted", "values": original, "updatedAt": 1}
    seed = '<script>localStorage.setItem(' + json.dumps("ticketbox:manual-draft:v1:" + ref) + ',' + \
        json.dumps(json.dumps(record)) + ');location.hash="#manual-' + ref + '";</script>'
    environment = Environment(loader=ChoiceLoader([DictLoader({"base.html": '<html><head><meta charset="utf-8">' +
        seed + '{% block page_scripts %}{% endblock %}</head><body>{% block content %}{% endblock %}</body></html>'}),
        FileSystemLoader(_REPO_ROOT / "backend/app/templates/web")]), autoescape=select_autoescape(["html"]))
    body = environment.get_template("expense_new.html").render(manual_draft_scope=scope, manual_draft_result="",
        form_ledger_id="ledger", form_device_public_id="device", form_home_currency_code="CNY", client_ref="b" * 32,
        values={"currency_code": "CNY"}, currency_options=["CNY"], category_options=[], edit_return_fields={},
        time_form={**time_values, "wall_time": "2026-11-01T01:30:15", "wall_input_type": "datetime-local", "offset_options": []},
        csrf_token="synthetic", currency_input={}, asset_version="time-contract")
    for name in ("manual-drafts.js", "manual-entry.js"):
        body = body.replace(f'/static/web/{name}?v=time-contract', (_REPO_ROOT / "backend/app/static/web" / name).as_uri())
    body += '<script>const timer=setInterval(()=>{const form=document.querySelector("[data-manual-draft-scope]");' + \
        'if(form.dataset.manualDraftState==="submitted"){clearInterval(timer);window.__webConsumerProbe={' + \
        'values:Object.fromEntries(new FormData(form).entries()),record:JSON.parse(localStorage.getItem(' + \
        json.dumps("ticketbox:manual-draft:v1:" + ref) + '))};}},25);</script>'
    page = _write_fixture(tmp_path, "original-time.html", body)
    probe = _evaluate_fixture(tmp_path, page=page, width=390, height=960, profile_name="edge-original-time")
    assert probe["values"]["spent_at"] == raw, "Reopening changed the original command's known instant"
    assert probe["values"]["client_ref"] == ref and probe["record"] == record


def test_income_create_original_form_draft_survives_refresh_in_real_edge(tmp_path: Path) -> None:
    """Real template consumer only; financial creation is a separate PostgreSQL gate."""
    edge = _discover_edge()
    templates = _REPO_ROOT / "backend/app/templates/web"
    static = (_REPO_ROOT / "backend/app/static").resolve()
    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
                        '<script>window.__incomeScriptErrors=[];'
                        'window.addEventListener("error",e=>window.__incomeScriptErrors.push(e.message));</script>'
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
            if len(posts) in {1, 3}:
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
        {"currency": "CNY", "month": "2026-10", "key": "aa740c64-6e8d-45e8-80fd-5dd26a2f7126"},
    ], requests
    assert len(posts) == 3, posts
    assert posts[0] == posts[1], posts
    for name, value in submitted.items():
        assert posts[0][name] == value, posts
    assert posts[0]["ledger_id"] == scope["ledgerId"], posts
    assert json.loads(posts[0]["draft_scope"]) == scope, posts
    assert posts[2]["idempotency_key"] == "aa740c64-6e8d-45e8-80fd-5dd26a2f7126"
    assert posts[2]["label"] == "已核对后不再续办的计划" and posts[2]["amount_yuan"] == "80.00"
    assert probe["discarded"]["removed"] and probe["discarded"]["newFormAvailable"], probe
    assert "不会撤销已发出的请求或已保存的计划" in probe["discarded"]["confirmation"], probe


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


def test_income_edit_keeps_original_draft_beside_current_facts_in_real_edge(tmp_path: Path) -> None:
    """Actual editor, storage and navigation; database mutation is tested separately."""
    edge = _discover_edge()
    static = (_REPO_ROOT / "backend/app/static").resolve()
    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
            '<script>window.__incomeScriptErrors=[];'
            'window.addEventListener("error",e=>window.__incomeScriptErrors.push(e.message));</script>'
            '{% block page_scripts %}{% endblock %}</head><body>{% block content %}{% endblock %}</body></html>'}),
        FileSystemLoader(_REPO_ROOT / "backend/app/templates/web"),
    ]), autoescape=select_autoescape(["html"]))
    template = environment.get_template("income_edit.html")
    scope = {"datasetId": "income-dataset", "clientGeneration": "income-generation",
        "accountId": "income-account", "ledgerId": "income-ledger", "deviceId": "income-device"}
    original_key = "c8127d5c-0796-4d86-8821-bc5a41bc0053"
    newer_key = "51d57734-f84f-4cbc-8722-3159c2443337"
    peer_key = "e77a6f42-5ca0-439a-860f-47e4c61c33de"
    requests, posts, missing_resources = [], [], []

    def editor_body(public_id, month):
        peer = public_id == "income-peer"
        newer = any(item["public_id"] == public_id for item in requests)
        key = peer_key if peer else newer_key if newer else original_key
        current = {"label": "另一项收入" if peer else "另一端已修改" if newer else "服务器已有计划",
            "source_type": "salary", "frequency": "monthly", "income_month": "",
            "amount_yuan": "800" if peer else "9999" if newer else "1000", "pay_day": "10",
            "expected_row_version": "2" if peer else "8" if newer else "7"}
        plan = {**current, "public_id": public_id, "status": "archived" if posts else "active", "home_currency_code": "JPY",
            "row_version": int(current["expected_row_version"])}
        requests.append({"public_id": public_id, "month": month, "key": key})
        return template.render(plan=plan, current=current,
            values={**current, "intent_month": month, "idempotency_key": key},
            income_draft_scope=scope, income_draft_result="", can_write=True,
            currency_input={"currency_code": "JPY", "currency_symbol": "¥", "amount_input_hint": "整数日元",
                "inputmode": "numeric", "amount_placeholder": "0"},
            selected_ledger_id=scope["ledgerId"], error=None, conflict=False, permission_refused=False,
            review_month="2026-10", asset_version="income-edit-contract",
            csrf_field='<input type="hidden" name="csrf_token" value="synthetic-not-a-credential">').encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body, *, content_type="text/html; charset=utf-8", status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                self.reply(b'<!doctype html><html><head><meta charset="utf-8"></head><body>'
                    b'<script src="/probe.js"></script></body></html>')
                return
            if parsed.path in {"/web/income-plans/income-original/edit", "/web/income-plans/income-peer/edit"}:
                self.reply(editor_body(parsed.path.split("/")[-2], parse_qs(parsed.query)["intent_month"][0]))
                return
            if parsed.path == "/web/income-plans":
                self.reply(b"<!doctype html><html><body>Income list after acknowledgement</body></html>")
                return
            if parsed.path == "/probe.js":
                self.reply((_REPO_ROOT / "backend/tests/fixtures/income_edit_draft_refresh_probe.js").read_bytes(),
                    content_type="text/javascript")
                return
            if parsed.path.startswith("/static/"):
                resource = (static / parsed.path.removeprefix("/static/")).resolve()
                if resource.is_relative_to(static) and resource.is_file():
                    self.reply(resource.read_bytes(), content_type="text/javascript")
                    return
                missing_resources.append(parsed.path)
            self.reply(b"not found", status=404)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=policy.default).parsebytes(
                f'Content-Type: {self.headers["Content-Type"]}\r\nMIME-Version: 1.0\r\n\r\n'.encode() + raw)
            fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode("utf-8")
                for part in message.iter_parts()}
            posts.append({"path": self.path, "fields": fields})
            if len(posts) == 1:
                self.reply(b'{"message":"Receipt unavailable"}', content_type="application/json", status=503)
                return
            body = {"ack": {"scope": scope, "clientRef": original_key},
                "receipt": {"public_id": "income-original", "row_version": 8, "amount_cents": 1200},
                "next": "/web/income-plans?ledger_id=income-ledger"}
            self.reply(json.dumps(body).encode(), content_type="application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def prepare_url(_attempt):
        requests.clear()
        posts.clear()
        missing_resources.clear()
        return f"http://127.0.0.1:{server.server_port}/"

    try:
        probe = _edge_cdp().evaluate_page(edge, profile=tmp_path / "edge-income-edit-draft",
            prepare_url=prepare_url, width=1024, height=768, expression="window.__incomeEditDraftProbe || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert missing_resources == [], missing_resources
    assert isinstance(probe, dict) and probe.get("error") is None, probe
    expected = {"label": "九月调薪原稿", "amount_yuan": " 001200 ", "source_type": "freelance",
        "frequency": "monthly", "income_month": "2026-11", "pay_day": "23", "intent_month": "2026-09",
        "expected_row_version": "7", "idempotency_key": original_key}
    assert probe["before"]["fields"] == expected, probe
    assert probe["after"]["fields"] == expected, f"reload replaced the original income correction: {probe}"
    assert probe["after"]["navigationType"] == "reload" and probe["after"]["hash"] == probe["before"]["hash"], probe
    assert "另一端已修改" in probe["after"]["current"], probe
    assert probe["reopened"]["fields"] == expected and "JPY" in probe["reopened"]["amountLabel"], probe
    assert "2026-09" in probe["reopened"]["intentNotice"] and "2026-10" not in probe["reopened"]["intentNotice"], probe
    assert probe["peer"]["fields"] == {"label": "另一项收入", "amount_yuan": "800", "source_type": "salary",
        "frequency": "monthly", "income_month": "", "pay_day": "10", "intent_month": "2026-10",
        "expected_row_version": "2", "idempotency_key": peer_key}, probe
    assert probe["originalAfterPeer"]["fields"] == expected, probe
    submitted = {**expected, "amount_yuan": "1200"}
    assert probe["unknown"]["fields"] == submitted and probe["frozen"], probe
    assert probe["archived"] and probe["archivedOriginal"]["fields"] == submitted, probe
    assert probe["accepted"] and probe["remainingOriginal"] is None, probe
    assert len(posts) == 2 and posts[0] == posts[1], posts
    assert posts[0]["path"] == "/web/income-plans/income-original/edit"
    assert posts[0]["fields"] == {**submitted, "ledger_id": "income-ledger", "home_currency_code": "JPY",
        "public_id": "income-original", "csrf_token": "synthetic-not-a-credential", "draft_scope": json.dumps(scope, separators=(",", ":"))}
    assert requests == [{"public_id": "income-original", "month": "2026-09", "key": original_key},
        {"public_id": "income-original", "month": "2026-09", "key": newer_key},
        {"public_id": "income-original", "month": "2026-10", "key": newer_key},
        {"public_id": "income-peer", "month": "2026-10", "key": peer_key},
        {"public_id": "income-original", "month": "2026-10", "key": newer_key}], requests


@pytest.mark.parametrize("kind", ["create", "edit"])
def test_goal_original_input_survives_reload_and_reopening_in_real_edge(tmp_path: Path, kind: str) -> None:
    """Real goal templates and storage; current projections cannot replace intent."""
    static = (_REPO_ROOT / "backend/app/static").resolve()
    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
            '{% block page_scripts %}{% endblock %}</head><body>{% block content %}{% endblock %}</body></html>'}),
        FileSystemLoader(_REPO_ROOT / "backend/app/templates/web"),
    ]), autoescape=select_autoescape(["html"]))
    template = environment.get_template("goals.html" if kind == "create" else "goal_edit.html")
    scope = {"datasetId": "goal-dataset", "clientGeneration": "goal-generation", "accountId": "goal-account",
        "ledgerId": "goal-ledger", "deviceId": "goal-device"}
    original_key, newer_key = "091b6930-3f0c-4070-b8ef-5b0f1a1d0022", "ff626aac-4e4b-407a-91e2-ec188f112866"
    path = "/web/goals" if kind == "create" else "/web/goals/goal-original/edit"
    action = "/web/goals/create" if kind == "create" else path
    fields = ["name", "target_amount_yuan", "category", "month", "home_currency_code", "idempotency_key"]
    if kind == "edit":
        fields += ["expected_row_version", "return_category", "return_month"]
    spec = {"kind": kind, "action": action, "fields": fields,
        "open": path + "?ledger_id=goal-ledger&return_category=food&return_month=2026-09",
        "reopen": path + "?ledger_id=goal-ledger&month=2026-10",
        "input": {"name": "九月原目标", "target_amount_yuan": " 001200 ", "category": "原分类"}}
    visits, posts, missing = [], [], []

    def goal_page(query):
        newer = bool(visits)
        visits.append(path)
        currency = "CNY" if newer and kind == "create" else "JPY"
        current = {"name": "另一端已修改" if newer else "已有目标", "month": "2026-10" if newer else "2026-09",
            "category": "交通", "target_amount_yuan": "9999" if newer else "1000",
            "home_currency_code": currency, "expected_row_version": "8" if newer else "7"}
        if kind == "create":
            current.update(name="", category="", target_amount_yuan="")
        values = {**current, "idempotency_key": newer_key if newer else original_key,
            "return_category": query.get("return_category", [""])[0], "return_month": query.get("return_month", [""])[0]}
        return template.render(values=values, current=current, month=current["month"], goals=[], include_archived=False,
            goal={"public_id": "goal-original", "status": "archived" if posts else "active"}, can_write=True, currency_matches=True,
            form_currency={"currency_code": currency, "amount_input_hint": "整数日元" if currency == "JPY" else "两位小数",
                "inputmode": "numeric" if currency == "JPY" else "decimal", "amount_example": "0"},
            selected_ledger_id=scope["ledgerId"], goal_draft_scope=scope, goal_draft_result="",
            category_return_url="", current_edit_url=path, error=None, message=None, conflict=False,
            asset_version="goal-continuation", csrf_field='<input type="hidden" name="csrf_token" value="synthetic">').encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body, *, content_type="text/html; charset=utf-8", status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            requested = urlsplit(self.path).path
            if requested == path:
                self.reply(goal_page(parse_qs(urlsplit(self.path).query)))
                return
            if requested in {"/", "/web/categories", "/web/goals"}:
                self.reply(b'<!doctype html><html><head><meta charset="utf-8"></head><body><script src="/probe.js"></script></body></html>'
                    if requested == "/" else b"<!doctype html><html><body>Original task after acknowledgement</body></html>")
                return
            if requested == "/probe.js":
                self.reply(('window.__goalDraftCase=' + json.dumps(spec) + ';\n').encode() +
                    (_REPO_ROOT / "backend/tests/fixtures/goal_draft_refresh_probe.js").read_bytes(), content_type="text/javascript")
                return
            if requested.startswith("/static/"):
                resource = (static / requested.removeprefix("/static/")).resolve()
                if resource.is_relative_to(static) and resource.is_file():
                    self.reply(resource.read_bytes(), content_type="text/javascript")
                    return
                missing.append(requested)
            self.reply(b"not found", status=404)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=policy.default).parsebytes(
                f'Content-Type: {self.headers["Content-Type"]}\r\nMIME-Version: 1.0\r\n\r\n'.encode() + raw)
            submitted = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode("utf-8")
                for part in message.iter_parts()}
            posts.append({"path": self.path, "fields": submitted})
            if len(posts) == 1:
                self.reply(b'{"message":"Receipt unavailable"}', content_type="application/json", status=503)
                return
            destination = "/web/goals?ledger_id=goal-ledger&month=2026-09" if kind == "create" else \
                "/web/categories?ledger_id=goal-ledger&month=2026-09#category-food"
            body = {"ack": {"scope": scope, "clientRef": original_key},
                "receipt": {"public_id": "goal-original", "row_version": 8, "target_amount_cents": 1200}, "next": destination}
            self.reply(json.dumps(body).encode(), content_type="application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def prepare_url(_attempt):
        visits.clear()
        posts.clear()
        missing.clear()
        return f"http://127.0.0.1:{server.server_port}/"

    try:
        probe = _edge_cdp().evaluate_page(_discover_edge(), profile=tmp_path / ("edge-goal-" + kind),
            prepare_url=prepare_url, width=1024, height=768, expression="window.__goalDraftProbe || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert missing == [], missing
    assert isinstance(probe, dict) and probe.get("error") is None, probe
    _assert_original_goal_recovered(probe, spec, original_key, kind, posts, scope)


def _assert_original_goal_recovered(probe, spec, original_key, kind, posts, scope):
    assert len(posts) == 2 and posts[0] == posts[1], posts
    sent = {**probe["before"]["fields"], "ledger_id": scope["ledgerId"], "csrf_token": "synthetic",
        "draft_scope": json.dumps(scope, separators=(",", ":"))}
    if kind == "edit":
        sent["public_id"] = "goal-original"
    assert posts[0] == {"path": spec["action"], "fields": sent}, posts
    expected = {**spec["input"], "month": "2026-09", "home_currency_code": "JPY", "idempotency_key": original_key}
    if kind == "edit":
        expected.update(expected_row_version="7", return_category="food", return_month="2026-09")
    assert probe["before"]["fields"] == expected, probe
    assert probe["after"]["fields"] == expected, f"reload replaced the original {kind} goal: {probe}"
    assert probe["after"]["navigationType"] == "reload", probe
    assert probe["reopened"]["fields"] == expected and "JPY" in probe["reopened"]["amountLabel"], probe
    if kind == "edit":
        assert "另一端已修改" in probe["reopened"]["current"], probe
        assert probe["archived"] and probe["destination"] == "/web/categories?ledger_id=goal-ledger&month=2026-09#category-food", probe
    else:
        assert probe["destination"] == "/web/goals?ledger_id=goal-ledger&month=2026-09", probe
    assert probe["unknown"]["fields"] == probe["unresolved"]["fields"] == expected, probe
    assert probe["frozen"] and probe["remaining"] is None, probe
