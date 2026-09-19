"""Real PostgreSQL/Web continuation, same admitted bytes and original receipts."""

from urllib.parse import parse_qs, urlsplit

import pytest

from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._infra.assets import PNG_BYTES
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
from tests.test_original_attachment_api import _bill, _financial_snapshot

pytestmark = pytest.mark.real_db


def _browser(client, identity):
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity), domain=PUBLIC_HOST, path="/")
    return browser


def _form(browser, expense_id, operation):
    page = browser.get(f"/web/expenses/{expense_id}/original?ledger_id=owner")
    assert page.status_code == 200, page.text
    suffix = f"/original/{operation}"
    return next((action, fields) for action, fields in hidden_post_forms(page.text).items()
                if urlsplit(action).path.endswith(suffix))


def test_web_actual_image_review_and_ack_replay_do_not_rebaseline_changed_bytes(client, identity):
    expense_id, saved, source = _bill(client, identity, legacy=True)
    original = _financial_snapshot(expense_id)
    browser = _browser(client, identity)
    action, fields = _form(browser, expense_id, "verify")
    assert fields["reviewed_sha256"] == ""
    image = browser.get(f"/web/expenses/{expense_id}/image?ledger_id=owner")
    assert image.status_code == 200 and image.content == source.read_bytes()
    fields["reviewed_sha256"] = image.headers["etag"].strip('"')
    headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"}
    accepted = browser.post(action, data=fields, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["receipt"]["sha256"] == saved.image_hash
    source.write_bytes(b"changed after the accepted review")
    replay = browser.post(action, data=fields, headers=headers)
    assert replay.status_code == 200 and replay.json() == accepted.json()
    assert browser.get(f"/web/expenses/{expense_id}/original/health").json()["state"] == "corrupt"
    assert _financial_snapshot(expense_id) == original


def test_web_replenishment_refuses_other_file_stale_occ_and_replays_original_acceptance(client, identity) -> None:
    expense_id, saved, source = _bill(client, identity)
    original = _financial_snapshot(expense_id)
    browser = _browser(client, identity)
    source.unlink()
    action, fields = _form(browser, expense_id, "replenish")
    headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"}
    # Valid alternative image reaches identity admission; it is not a parser error.
    from io import BytesIO

    from PIL import Image
    different = BytesIO()
    Image.new("RGB", (4, 4), "red").save(different, format="PNG")
    refused = browser.post(action, data=fields, headers=headers,
        files={"file": ("other.png", different.getvalue(), "image/png")})
    assert refused.status_code == 409 and refused.json()["error"] == "image_replenishment_mismatch"
    assert browser.get(f"/web/expenses/{expense_id}/original/health").json()["state"] == "missing"
    stale_query = parse_qs(urlsplit(action).query)
    stale_query["expected_row_version"] = [str(int(stale_query["expected_row_version"][0]) + 1)]
    stale = browser.post(urlsplit(action).path, params={key: value[0] for key, value in stale_query.items()},
        data=fields, headers=headers, files={"file": ("receipt.png", PNG_BYTES, "image/png")})
    assert stale.status_code == 409 and stale.json()["error"] == "state_conflict"
    action, fields = _form(browser, expense_id, "replenish")
    accepted = browser.post(action, data=fields, headers=headers,
        files={"file": ("receipt.png", PNG_BYTES, "image/png")})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["receipt"]["expense_id"] == expense_id
    replay = browser.post(action, data=fields, headers=headers,
        files={"file": ("receipt.png", PNG_BYTES, "image/png")})
    assert replay.status_code == 200 and replay.json() == accepted.json()
    health = browser.get(f"/web/expenses/{expense_id}/original/health").json()
    assert health["state"] == "verified" and health["expected_sha256"] == saved.image_hash
    assert _financial_snapshot(expense_id) == original
