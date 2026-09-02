"""Focused W1 Warm Ledger consumer contracts kept separate from the older inbox suite."""

from __future__ import annotations

import re

from _web_bulk_test_support import seed_pending_with_amount as _seed_pending_with_amount
from fastapi.testclient import TestClient


def test_web_pending_touch_targets_and_file_picker_markup(
    web_client: TestClient, *, identity
) -> None:
    """Touch targets improve without replacing native upload/OCC owners."""
    eid = _seed_pending_with_amount(
        web_client,
        "9.00",
        "X",
        category="餐饮",
        identity=identity,
    )
    response = web_client.get("/web/pending?ledger_id=owner")
    assert response.status_code == 200
    body = response.text

    row_label = re.search(
        r'<label class="check-cell">\s*<input class="checkbox row-check"[^>]+>', body
    )
    assert row_label is not None
    assert re.search(
        r'<label class="check-cell">\s*<input class="checkbox" id="check-all"', body
    )
    row_input = row_label.group(0)
    assert f'aria-label="选择账单 #{eid}"' in row_input
    assert 'form="bulk-form"' in row_input
    assert 'data-row-version="' in row_input
    assert 'name="expense_snapshot"' in row_input

    file_input = re.search(r'<input class="file-picker-input"[^>]+>', body)
    assert file_input is not None
    file_tag = file_input.group(0)
    for contract in (
        'type="file"',
        'name="file"',
        'accept="image/*"',
        "required",
        'aria-label="选择小票图片"',
    ):
        assert contract in file_tag
    # 原生 input 常显是唯一事实 owner: 选中文件名由浏览器原生呈现, 无 JS /
    # JS 失败时用户仍看到将上传的文件; 代理 label 与 JS 文件名槽整体退役。
    assert "file-picker-label" not in body
    assert "data-file-picker-name" not in body
    assert 'data-inbox-capture enctype="multipart/form-data"' in body
    capture_form = re.search(r'<form[^>]*data-inbox-capture[^>]*>', body)
    assert capture_form is not None
    assert 'id="capture"' in capture_form.group(0)


def test_inbox_empty_state_shows_mascot_illustration(web_client: TestClient) -> None:
    """The empty queue uses the real decorative brand asset."""
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    state = re.search(
        r'<div class="product-state">.*?<a class="product-state-action"',
        response.text,
        re.S,
    )
    assert state is not None
    assert '<div class="product-state-figure" aria-hidden="true">' in state.group(0)
    assert '<img src="/static/web/product/mascot/jiajia-dozing.png" alt=""' in state.group(0)


def test_inbox_row_meta_drops_engineering_id_and_keeps_command_contract(
    web_client: TestClient, *, identity
) -> None:
    """Human-facing row copy improves while CSRF/OCC and result copy remain intact."""
    eid = _seed_pending_with_amount(
        web_client,
        "9.00",
        "盒马",
        category="餐饮",
        identity=identity,
    )
    response = web_client.get("/web/pending?ledger_id=owner")
    assert response.status_code == 200
    body = response.text

    assert '<div class="exp-meta">#' not in body
    assert f'aria-label="选择账单 #{eid}"' in body
    drawer = web_client.get(f"/web/expenses/{eid}/edit?ledger_id=owner&fragment=1")
    assert drawer.status_code == 200
    assert f"#{eid}" in drawer.text

    row_form = re.search(
        r'<form class="exp-row-action" method="post" action="/web/review/bulk">.*?</form>',
        body,
        re.S,
    )
    assert row_form is not None
    form_html = row_form.group(0)
    assert 'name="csrf_token"' in form_html
    assert 'name="expense_snapshot"' in form_html
    command = (
        '<button class="product-button product-button--primary" type="submit" '
        'name="action" value="confirm_ready">确认入账</button>'
    )
    assert command in form_html
    assert command in body
