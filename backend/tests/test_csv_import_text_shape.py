"""Issue #271: CSV import reports over-long text and tags as row errors.

The staged CSV preview writes each parsed row into ``csv_import_rows`` and
apply copies it into ``expenses`` and the tag mirror. Merchant, category and
each normalized tag (name and casefold key) have database length limits; a
row that exceeds them must be a specific preview error, never a database
failure, and must not stop the valid rows of the same batch.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense, Tag

LONG_MERCHANT = "店" * 256
LONG_CATEGORY = "类" * 65
LONG_TAG = "签" * 65
LONG_SOURCE = "源" * 65
# 33 characters, but casefold turns each "ß" into "ss": a 66-character lookup key.
CASEFOLD_TAG = "ß" * 33


def _create(client: TestClient, identity, rows: list[str]):
    body = "\n".join(["amount_yuan,merchant,category,tags,source", *rows, ""]).encode("utf-8")
    return client.post("/api/imports/csv", headers=identity.app_headers,
                       files={"csv_file": ("shape.csv", BytesIO(body), "text/csv")})


@pytest.mark.parametrize(("row", "message"), [
    (f"1.00,{LONG_MERCHANT},餐饮,,", "商户最多 255 个字符"),
    (f"1.00,店,{LONG_CATEGORY},,", "分类最多 64 个字符"),
    (f"1.00,店,餐饮,{LONG_TAG},", "单个标签标准化后最多 64 个字符"),
    (f"1.00,店,餐饮,{CASEFOLD_TAG},", "单个标签标准化后最多 64 个字符"),
    (f"1.00,店,餐饮,,{LONG_SOURCE}", "来源最多 64 个字符"),
    (f"1.00,{LONG_MERCHANT},{LONG_CATEGORY},,", "商户最多 255 个字符；分类最多 64 个字符"),
], ids=["merchant", "category", "tag", "tag-casefold", "source", "merchant-and-category"])
def test_over_long_text_is_a_row_error_and_valid_rows_still_apply(client: TestClient, *, identity, row: str, message: str) -> None:
    created = _create(client, identity, ["2.00,好店,餐饮,早餐,", row])
    assert created.status_code == 201, created.text
    batch = created.json()
    assert (batch["valid_rows"], batch["error_rows"]) == (1, 1)

    rows = client.get(f"/api/imports/csv/{batch['public_id']}/rows", headers=identity.app_headers)
    assert rows.status_code == 200, rows.text
    bad = next(item for item in rows.json()["items"] if item["line_number"] == 3)
    assert bad["status"] == "error"
    assert bad["error_code"] == "text_too_long"
    assert bad["error_message"] == message

    applied = client.post(f"/api/imports/csv/{batch['public_id']}/apply", headers=identity.app_headers,
                          json={"batch_size": 10})
    assert applied.status_code == 200, applied.text
    assert applied.json()["inserted_count"] == 1
    with SessionLocal() as db:
        merchants = [value for (value,) in db.query(Expense.merchant).filter(Expense.merchant.in_(["好店", "店"]))]
        assert merchants == ["好店"]
        assert db.query(Tag).filter(Tag.name.in_([LONG_TAG, CASEFOLD_TAG])).count() == 0
