"""Shared fixture and markup helpers for Web bulk-action tests."""

from __future__ import annotations

from html.parser import HTMLParser

from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient


def create_pending(client: TestClient, *, identity) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def seed_pending_with_amount(
    web_client: TestClient,
    amount_yuan: str = "10.00",
    merchant: str = "测试",
    *,
    identity,
) -> int:
    expense_id = create_pending(web_client, identity=identity)
    response = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": amount_yuan,
            "merchant": merchant,
            "category": "其他",
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert response.status_code in {303, 307}, response.text
    return expense_id


def row_version(
    web_client: TestClient,
    expense_id: int,
    *,
    identity,
) -> int:
    response = web_client.get(
        f"/api/expenses/{expense_id}",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["row_version"])


def bulk_snapshot_fields(
    web_client: TestClient,
    expense_ids: list[int],
    *,
    identity,
) -> dict[str, list[str]]:
    return {
        "expense_ids": [str(expense_id) for expense_id in expense_ids],
        "expected_row_version": [
            str(row_version(web_client, expense_id, identity=identity)) for expense_id in expense_ids
        ],
    }


class _CheckboxNestingProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._open_tags: list[str] = []
        self.checkbox_count = 0
        self.checkbox_inside_link = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "input" and attributes.get("type") == "checkbox":
            self.checkbox_count += 1
            self.checkbox_inside_link = self.checkbox_inside_link or "a" in self._open_tags
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
        }:
            self._open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._open_tags:
            return
        reverse_index = self._open_tags[::-1].index(tag)
        del self._open_tags[len(self._open_tags) - reverse_index - 1 :]


def assert_native_checkboxes_are_outside_links(html: str) -> None:
    probe = _CheckboxNestingProbe()
    probe.feed(html)
    assert probe.checkbox_count >= 2
    assert not probe.checkbox_inside_link
