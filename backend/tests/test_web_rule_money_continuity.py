"""Captured rule money survives native Web editing, replay and refusal."""

import json
from contextlib import closing
from uuid import uuid4

import pytest

from tests._web_native_form_support import hidden_post_forms


def _rule(client, identity):
    result = client.post("/api/rules/categories",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"keyword": "旅行商店", "category": "购物", "priority": 10,
            "amount_min_cents": 1200, "home_currency_code": "JPY"})
    assert result.status_code == 200, result.text
    return result.json()


def _editor(client, rule):
    action = f'/web/rules/{rule["id"]}/edit'
    page = client.get(action, params={"ledger_id": "owner"})
    assert page.status_code == 200, page.text
    assert 'name="amount_min_yuan"' in page.text and 'value="1200"' in page.text
    fields = hidden_post_forms(page.text)[action]
    fields.update(keyword=rule["keyword"], category=rule["category"], priority="10",
        amount_min_yuan="1500", amount_max_yuan="", source_contains="", tag_contains="")
    return action, fields


def test_jpy_rule_edit_and_replay_use_original_units_under_cny_runtime(web_client, identity):
    rule = _rule(web_client, identity)
    page = web_client.get("/web/rules?ledger_id=owner")
    assert "JPY ¥1,200" in page.text and "JPY ¥12.00" not in page.text
    action, fields = _editor(web_client, rule)
    assert fields["home_currency_code"] == "JPY"
    saved = web_client.post(action, data=fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    current = next(row for row in web_client.get("/api/rules/categories",
        headers=identity.app_headers).json() if row["id"] == rule["id"])
    assert current["amount_min_cents"] == 1500 and current["home_currency_code"] == "JPY"
    assert current["row_version"] == rule["row_version"] + 1
    later = web_client.patch(f'/api/rules/categories/{rule["id"]}',
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": current["row_version"], "amount_min_cents": 1700,
            "home_currency_code": "JPY"})
    assert later.status_code == 200, later.text
    replay = web_client.post(action, data=fields, follow_redirects=False)
    assert replay.status_code == 303, replay.text
    after = next(row for row in web_client.get("/api/rules/categories",
        headers=identity.app_headers).json() if row["id"] == rule["id"])
    assert after == later.json()


@pytest.mark.parametrize(("currency", "raw", "status"), [("", "001200", 422), ("CNY", "1200.00", 409)])
def test_rule_currency_refusal_keeps_inputs_and_cannot_rekey_as_current(web_client, identity, currency, raw, status):
    rule = _rule(web_client, identity)
    action, fields = _editor(web_client, rule)
    fields.update(home_currency_code=currency, amount_min_yuan=raw)
    refused = web_client.post(action, data=fields)
    assert refused.status_code == status, refused.text
    assert f'value="{raw}"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    original_names = ("home_currency_code", "idempotency_key", "expected_row_version", "ledger_id")
    for name in original_names:
        assert retained[name] == fields[name]
    assert ">保存规则</button>" not in refused.text
    reviewed = web_client.post(action, data={**fields, "review_latest": "true"})
    assert reviewed.status_code == 200, reviewed.text
    reviewed_fields = hidden_post_forms(reviewed.text)[action]
    for name in original_names:
        assert reviewed_fields[name] == fields[name]
    after = next(row for row in web_client.get("/api/rules/categories",
        headers=identity.app_headers).json() if row["id"] == rule["id"])
    assert after == rule


def test_rule_stop_toggle_ack_retry_does_not_enable_again(web_client, identity):
    rule = _rule(web_client, identity)
    action = f'/web/rules/{rule["id"]}/toggle'
    fields = hidden_post_forms(web_client.get("/web/rules?ledger_id=owner").text)[action]
    assert fields["enabled"] == "false"
    for _ in range(2):
        response = web_client.post(action, data=fields, follow_redirects=False)
        assert response.status_code == 303, response.text
    after = next(row for row in web_client.get("/api/rules/categories",
        headers=identity.app_headers).json() if row["id"] == rule["id"])
    assert after["enabled"] is False and after["row_version"] == rule["row_version"] + 1


def _definition_input(web, rule=None):
    action = f'/web/rules/{rule["id"]}/edit' if rule else "/web/rules/create"
    page = web.get(action + "?ledger_id=owner" if rule else "/web/rules?ledger_id=owner&view=new")
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)[action]
    fields.update(keyword="  浏览器原规则  ", category="购物", priority="10",
        amount_min_yuan="1500" if rule else "", amount_max_yuan="", source_contains="", tag_contains="")
    return action, fields


@pytest.mark.parametrize("editing", [False, True])
def test_public_rule_definition_receipt_survives_deletion_but_not_revoked_permission(client, identity, editing):
    from app.routes.web_auth import SESSION_COOKIE_NAME
    from tests._infra.merchant_catalog import demote_owner_ledger_to_viewer
    from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

    original = _rule(client, identity) if editing else None
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity))
        action, fields = _definition_input(web, original)
        headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"}
        accepted = web.post(action, data=fields, headers=headers)
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()
        assert result["ack"] == {"scope": json.loads(fields["draft_scope"]), "clientRef": fields["idempotency_key"]}
        rule = result["receipt"]
        deleted = client.request("DELETE", f'/api/rules/categories/{rule["id"]}',
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={"expected_row_version": rule["row_version"]})
        assert deleted.status_code == 200, deleted.text
        replay = web.post(action, data=fields, headers=headers)
        assert replay.status_code == 200 and replay.json() == result
        assert rule["id"] not in {row["id"] for row in client.get("/api/rules/categories", headers=identity.app_headers).json()}
        demote_owner_ledger_to_viewer()
        assert web.post(action, data=fields, headers=headers).status_code == 403


@pytest.mark.parametrize("editing", [False, True])
def test_rule_definition_rejects_wrong_browser_binding_csrf_and_ledger_without_writes(client, identity, editing):
    from app.routes.web_auth import SESSION_COOKIE_NAME
    from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

    original = _rule(client, identity) if editing else None
    before = client.get("/api/rules/categories", headers=identity.app_headers).json()
    headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"}
    with closing(public_client()) as web, closing(public_client()) as another:
        web.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity))
        action, fields = _definition_input(web, original)
        assert web.post(action, data={**fields, "csrf_token": "invalid"}, headers=headers).status_code == 403
        wrong_ledger = web.post(action, data={**fields, "ledger_id": "gray"}, headers=headers)
        assert wrong_ledger.status_code == 409, wrong_ledger.text
        another.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity))
        _, fresh = _definition_input(another, original)
        refused = another.post(action, data={**fields, "csrf_token": fresh["csrf_token"]}, headers=headers)
        assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed"
    assert client.get("/api/rules/categories", headers=identity.app_headers).json() == before
