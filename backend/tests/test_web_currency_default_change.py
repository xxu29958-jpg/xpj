"""The native Desktop Owner form retains the original default-change command."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.errors import AppError, add_exception_handlers
from app.middleware import csrf
from app.routes import web_currency_adoption as page
from app.tenants import AuthContext
from tests._web_native_form_support import hidden_post_forms

PATH = "/web/currency-adoption/change"


@pytest.fixture
def owner_browser(monkeypatch):
    auth = AuthContext(7, "owner", "Owner", "ledger", "Ledger", 2, "desktop", "Desktop", "owner", "app")
    current = SimpleNamespace(state="ACTIVE", binding_revision=2, currency_contract_version=1,
        home_currency_code="CNY", allowed_home_currency_codes=("CNY", "JPY", "USD"),
        evidence_sha256="a" * 64, evidence_health="adoptable")
    db = Mock()
    saved = Mock(return_value=SimpleNamespace(home_currency_code="JPY", source_home_currency_code="CNY", binding_revision=3,
        changed_at="2026-09-09T09:00:00Z"))

    def verify(_db, supplied):
        if supplied.account_id != auth.account_id:
            raise AppError("permission_denied", status_code=403)
        return supplied

    def preview(_db, *, auth):
        verify(_db, auth)
        return current

    monkeypatch.setattr(page, "revalidate_currency_adoption_owner", verify)
    monkeypatch.setattr(page, "currency_change_preview", Mock(side_effect=preview), raising=False)
    monkeypatch.setattr(page, "change_currency_binding_for_installation_owner", saved, raising=False)
    monkeypatch.setattr(page, "adoption_preview", Mock(return_value=current))
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"synthetic-currency-browser-secret")
    app = FastAPI()
    app.include_router(page.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[page.LocalOnly.dependency] = lambda: None
    add_exception_handlers(app)

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.web_session_platform = request.headers.get("x-test-platform", "desktop")
        request.state.web_session_auth = auth if request.headers.get("x-test-account") != "other" else AuthContext(
            9, "member", "Member", "ledger", "Ledger", 3, "another", "Another", "owner", "app")
        return await call_next(request)

    app.middleware("http")(csrf.csrf_loopback_form_guard)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51111)) as client:
        yield SimpleNamespace(client=client, current=current, saved=saved, db=db, auth=auth)


def _draft(browser, **changes):
    response = browser.client.get("/web/currency-adoption", params={"change": "true"})
    assert response.status_code == 200, response.text
    fields = hidden_post_forms(response.text)[PATH]
    return {**fields, "home_currency_code": "JPY", "reason": "  出差后使用日元  ", **changes}


def _post(browser, fields, **kwargs):
    return browser.client.post(PATH, data=fields, headers={"Origin": "http://127.0.0.1", **kwargs}, follow_redirects=False)


def test_active_page_exposes_change_without_adoption_evidence_scan(owner_browser):
    response = owner_browser.client.get("/web/currency-adoption")
    assert response.status_code == 200
    assert 'href="/web/currency-adoption?change=true"' in response.text
    assert "修改默认币种" in response.text
    page.adoption_preview.assert_not_called()


def test_native_editor_has_no_preselected_currency_and_states_history_boundary(owner_browser):
    response = owner_browser.client.get("/web/currency-adoption?change=true")
    fields = hidden_post_forms(response.text)[PATH]
    assert fields["source_home_currency_code"] == "CNY"
    assert fields["expected_binding_revision"] == "2"
    assert fields["currency_contract_version"] == "1"
    assert UUID(fields["idempotency_key"]).version == 4
    assert "checked" not in response.text
    assert "不会改写历史记录的币种和金额" in response.text
    assert "还款通知" in response.text and 'class="currency-change-non-cny"' in response.text


def test_native_save_uses_original_key_revision_reason_and_original_receipt(owner_browser):
    fields = _draft(owner_browser)
    owner_browser.current.home_currency_code = "EUR"
    owner_browser.current.binding_revision = 8
    response = _post(owner_browser, fields)
    assert response.status_code == 200, response.text
    assert "本次修改已确认" in response.text and "JPY" in response.text
    assert "2026-09-09T09:00:00Z" in response.text
    assert "最新默认币种已设为 EUR" not in response.text
    args = owner_browser.saved.call_args.kwargs
    assert args == {"auth": owner_browser.auth, "idempotency_key": UUID(fields["idempotency_key"]),
        "expected_contract_version": 1, "home_code": "JPY", "expected_revision": 2,
        "reason": fields["reason"]}


def test_accepted_before_currency_comes_from_the_receipt_not_a_reposted_display_field(owner_browser):
    response = _post(owner_browser, _draft(owner_browser, source_home_currency_code="EUR"))
    assert response.status_code == 200
    assert "CNY → JPY" in response.text
    assert "EUR → JPY" not in response.text


@pytest.mark.parametrize("error", ["currency_binding_state_conflict", "idempotency_key_reused", "idempotency_key_in_progress",
    "client_upgrade_required", "currency_binding_already_active"])
def test_error_retains_every_original_field_and_never_claims_success(owner_browser, error):
    fields = _draft(owner_browser)
    owner_browser.saved.side_effect = AppError(error, status_code=409)
    owner_browser.current.home_currency_code = "USD"
    owner_browser.current.binding_revision = 9
    response = _post(owner_browser, fields)
    assert response.status_code == 409, response.text
    retained = hidden_post_forms(response.text)[PATH]
    for key in ("source_home_currency_code", "expected_binding_revision", "currency_contract_version", "idempotency_key"):
        assert retained[key] == fields[key]
    assert fields["reason"] in response.text and 'value="JPY" checked' in response.text
    assert "本次修改已确认" not in response.text
    assert 'name="review_latest" value="true"' in response.text
    owner_browser.db.rollback.assert_called_once()


def test_explicit_review_keeps_choice_and_reason_but_only_prepares_new_intent(owner_browser):
    fields = _draft(owner_browser)
    owner_browser.current.home_currency_code = "USD"
    owner_browser.current.binding_revision = 9
    response = _post(owner_browser, {**fields, "review_latest": "true"})
    assert response.status_code == 200
    prepared = hidden_post_forms(response.text)[PATH]
    assert prepared["source_home_currency_code"] == "USD"
    assert prepared["expected_binding_revision"] == "9"
    assert prepared["idempotency_key"] != fields["idempotency_key"]
    assert fields["reason"] in response.text and 'value="JPY" checked' in response.text
    owner_browser.saved.assert_not_called()


@pytest.mark.parametrize("field,value", [("idempotency_key", ""), ("expected_binding_revision", "wrong")])
def test_malformed_original_is_retained_without_command(owner_browser, field, value):
    fields = _draft(owner_browser, **{field: value})
    response = _post(owner_browser, fields)
    assert response.status_code == 422
    assert hidden_post_forms(response.text)[PATH][field] == value
    owner_browser.saved.assert_not_called()


@pytest.mark.parametrize("stage", ["command", "credential"])
def test_uncertain_database_response_retains_the_command_for_same_key_retry(owner_browser, monkeypatch, stage):
    fields = _draft(owner_browser)
    failure = OperationalError("COMMIT", {}, RuntimeError("connection closed"))
    if stage == "command":
        owner_browser.saved.side_effect = failure
    else:
        monkeypatch.setattr(page, "revalidate_currency_adoption_owner", Mock(side_effect=failure))
    response = _post(owner_browser, fields)
    assert response.status_code == 503
    retained = hidden_post_forms(response.text)[PATH]
    assert retained["idempotency_key"] == fields["idempotency_key"]
    assert retained["expected_binding_revision"] == "2"
    assert fields["reason"] in response.text and "原提交重试" in response.text
    assert "COMMIT" not in response.text and "connection closed" not in response.text


def test_same_currency_rejection_stays_a_clear_no_change(owner_browser):
    fields = _draft(owner_browser, home_currency_code="CNY")
    owner_browser.saved.side_effect = AppError("invalid_request", "已在使用这个默认币种。", status_code=422)
    response = _post(owner_browser, fields)
    assert response.status_code == 422
    assert "已在使用这个默认币种" in response.text and "本次修改已确认" not in response.text
    assert hidden_post_forms(response.text)[PATH]["idempotency_key"] == fields["idempotency_key"]


def test_csrf_and_non_owner_cannot_enter_change_owner(owner_browser):
    fields = _draft(owner_browser)
    missing_csrf = {key: value for key, value in fields.items() if key != "csrf_token"}
    assert _post(owner_browser, missing_csrf).status_code == 403
    assert _post(owner_browser, fields, **{"x-test-platform": "browser"}).status_code == 403
    assert _post(owner_browser, fields, **{"x-test-account": "other"}).status_code == 403
    owner_browser.saved.assert_not_called()


@pytest.mark.parametrize("claims,platform,visible", [([7], "desktop", True), ([9], "desktop", False),
    ([7, 9], "desktop", False), ([], "desktop", False), ([7], "browser", False)])
def test_real_account_menu_only_exposes_the_installation_owners_entry(owner_browser, monkeypatch, claims, platform, visible):
    from app.routes import web_common

    request = Request({"type": "http", "method": "GET", "path": "/web/confirmed", "scheme": "http",
        "server": ("127.0.0.1", 80), "query_string": b"", "headers": [],
        "state": {"web_session_platform": platform, "web_session_auth": owner_browser.auth}})
    monkeypatch.setattr(web_common, "require_runtime_home_currency_code", lambda _: "CNY")
    owner_browser.db.scalars.return_value = claims
    # Installation Owner authority is independent of the selected ledger's role.
    option = web_common.LedgerOption("ledger", "Ledger", "viewer", False, 0, 0)
    context = web_common._base_ctx(request, db=owner_browser.db, options=[option], selected_ledger_id="ledger")
    html = web_common.templates.get_template("_ledger_switcher.html").render(**context, q="", **csrf.csrf_context(request))
    assert ('href="/web/currency-adoption"' in html) is visible
    if visible:
        response = owner_browser.client.get("/web/currency-adoption")
        assert response.status_code == 200 and "修改默认币种" in response.text
    if platform == "browser":
        owner_browser.db.scalars.assert_not_called()
