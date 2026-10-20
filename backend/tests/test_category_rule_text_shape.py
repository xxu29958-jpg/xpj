"""Category-rule text longer than its column is a validation error, not a server error.

``keyword`` is VARCHAR(255); ``category``, ``source_contains`` and
``tag_contains`` are VARCHAR(64). Before these limits were declared on the
request schemas, an over-long value reached PostgreSQL and the request failed
with a 500 (``StringDataRightTruncation``) — from the API, the Android offline
rule edit and the Web rule form alike.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CategoryRule
from tests._web_rule_form_support import submit_rule_form

OVER_LONG = [("keyword", "词" * 256), ("category", "类" * 65), ("source_contains", "源" * 65), ("tag_contains", "签" * 65)]


def _headers(identity) -> dict[str, str]:
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create(client: TestClient, identity, **fields):
    return client.post("/api/rules/categories", headers=_headers(identity), json={"keyword": "咖啡", "category": "餐饮", **fields})


@pytest.mark.parametrize(("field", "value"), OVER_LONG, ids=[field for field, _ in OVER_LONG])
def test_api_create_and_update_reject_over_long_text(client: TestClient, *, identity, field: str, value: str) -> None:
    created = _create(client, identity, **{field: value})
    assert created.status_code == 422, created.text

    rule = _create(client, identity).json()
    updated = client.patch(f"/api/rules/categories/{rule['id']}", headers=_headers(identity),
                           json={"expected_row_version": rule["row_version"], field: value})
    assert updated.status_code == 422, updated.text
    with SessionLocal() as db:
        stored = db.get(CategoryRule, rule["id"])
        assert (stored.keyword, stored.category, stored.row_version) == ("咖啡", "餐饮", rule["row_version"])


def test_api_accepts_text_at_the_column_width(client: TestClient, *, identity) -> None:
    created = _create(client, identity, keyword="词" * 255, category="类" * 64, source_contains="源" * 64, tag_contains="签" * 64)
    assert created.status_code == 200, created.text
    assert created.json()["keyword"] == "词" * 255


def test_web_rule_form_keeps_the_over_long_draft_as_a_form_error(web_client: TestClient) -> None:
    draft = {"keyword": "词" * 256, "category": "餐饮", "priority": "100", "ledger_id": "owner"}
    response = submit_rule_form(web_client, "/web/rules/create", data=draft, follow_redirects=False)
    assert response.status_code == 422
    assert 'role="alert"' in response.text
    assert f'value="{draft["keyword"]}"' in response.text
