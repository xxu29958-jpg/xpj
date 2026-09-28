"""Real Edge consumer gate for the /web bulk bar (批选模式 + 异步反馈 aria 语义).

#218 C5a: only the bulk-bar slice lives here for now — the responsive-shell /
dashboard-refresh / confirm-modal consumer gates ride in with their own slices.
Skips cleanly on hosts without Microsoft Edge (CI lane that pins a real browser
runs it for real).
"""

from __future__ import annotations

import html
import importlib.util
import os
import shutil
import sys
import threading
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
        plan = {**current, "public_id": public_id, "status": "active", "home_currency_code": "JPY",
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
            posts.append(self.path)
            self.reply(b'{"error":"unexpected_submission"}', content_type="application/json", status=409)

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
    assert missing_resources == [] and posts == [], (missing_resources, posts)
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
    assert requests == [{"public_id": "income-original", "month": "2026-09", "key": original_key},
        {"public_id": "income-original", "month": "2026-09", "key": newer_key},
        {"public_id": "income-original", "month": "2026-10", "key": newer_key},
        {"public_id": "income-peer", "month": "2026-10", "key": peer_key}], requests
