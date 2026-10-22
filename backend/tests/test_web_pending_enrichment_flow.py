from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from _web_bulk_test_support import create_pending as _create_pending
from _web_bulk_test_support import seed_pending_with_amount as _seed_pending_with_amount
from api_contract_helpers import web_confirm_expense, web_reject_expense, web_save_expense, web_undo_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services.expense_service._enrich as enrichment_service
from app.database import SessionLocal
from app.models import BackgroundTask, Expense
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.ocr_service import OcrExtraction, OcrResult
from tests._infra.assets import PNG_BYTES


def test_inbox_duplicate_action_targets_the_real_review_case(
    web_client: TestClient, *, identity
) -> None:
    _seed_pending_with_amount(web_client, "9.00", "盒马", identity=identity)
    duplicate_id = _seed_pending_with_amount(
        web_client,
        "9.00",
        "盒马",
        identity=identity,
    )

    pending_body = web_client.get("/web/pending?ledger_id=owner").text
    duplicate_row = re.search(
        rf'<div class="exp-row" data-expense-id="{duplicate_id}">.*?'
        r'<div class="exp-flags">(.*?)</div>\s*</div>',
        pending_body,
        re.S,
    )
    assert duplicate_row is not None
    assert (
        f'href="/web/duplicates?ledger_id=owner#duplicate-{duplicate_id}">核对重复</a>'
        in duplicate_row.group(1)
    )

    review_body = web_client.get("/web/duplicates?ledger_id=owner").text
    assert f'id="duplicate-{duplicate_id}"' in review_body


def test_pending_watch_is_task_scoped_and_ignores_unrelated_expense_edits(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    with SessionLocal() as db:
        account_id = find_owner_account_id_for_ledger(db, ledger_id="owner")
        assert account_id is not None
        task = BackgroundTask(
            task_type="expense_enrichment",
            tenant_id="owner",
            initiated_by_account_id=account_id,
            status="queued",
            progress_total=1,
            source_expense_id=expense_id,
        )
        db.add(task)
        db.commit()
        task_public_id = task.public_id

    watch_url = f"/web/pending?ledger_id=owner&watch={task_public_id}"
    processing = web_client.get(watch_url)
    assert processing.status_code == 200
    assert "data-inbox-enrichment-watch" in processing.text
    assert "正在识别" in processing.text
    timeout = re.search(r'data-watch-timeout-ms="(\d+)"', processing.text)
    assert timeout is not None
    assert int(timeout.group(1)) > 12_000

    updated = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": "19.90",
            "merchant": "盒马",
            "category": "餐饮",
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert updated.status_code == 303, updated.text

    still_processing = web_client.get(watch_url)
    assert still_processing.status_code == 200
    assert "data-inbox-enrichment-watch" in still_processing.text
    assert "data-inbox-enrichment-terminal" not in still_processing.text

    with SessionLocal() as db:
        malformed = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert malformed is not None
        malformed.status = "completed"
        malformed.result_summary_json = "{}"
        db.commit()

    malformed_page = web_client.get(watch_url)
    assert 'data-enrichment-state="failed"' in malformed_page.text
    assert "自动识别失败，账单仍安全保留" in malformed_page.text

    with SessionLocal() as db:
        conflict = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert conflict is not None
        conflict.result_summary_json = json.dumps({"outcome": "conflict"})
        db.commit()

    conflict_page = web_client.get(watch_url)
    assert 'data-enrichment-state="conflict"' in conflict_page.text
    assert "你后来保存的修改已保留" in conflict_page.text


@pytest.mark.parametrize("task_status", ["running", "failed"])
@pytest.mark.parametrize("command", [web_confirm_expense, web_reject_expense])
def test_pending_feedback_retires_when_original_leaves_queue(web_client, identity, task_status, command):
    expense_id = _seed_pending_with_amount(web_client, identity=identity)
    with SessionLocal() as db:
        task = BackgroundTask(task_type="expense_enrichment", tenant_id="owner",
            initiated_by_account_id=find_owner_account_id_for_ledger(db, ledger_id="owner"),
            status=task_status, progress_total=1, source_expense_id=expense_id)
        db.add(task)
        db.commit()
        task_public_id = task.public_id
    watch_url = "/web/pending?" + urlencode({"ledger_id": "owner", "filter": "missing_amount",
        "watch": task_public_id, "msg": "小票已收到，正在识别；完成后本页会自动更新。", "flash_type": "success"})
    filtered = web_client.get(watch_url).text
    assert "data-inbox-enrichment-" in filtered, "筛选隐藏原单不等于原单离开待处理队列"
    assert f'data-expense-id="{expense_id}"' not in filtered
    if task_status == "running":
        assert f'watch={task_public_id}#recognition' in filtered, "筛选隐藏仍待处理原单时可继续查看进度"

    result = command(web_client, expense_id, identity=identity)
    assert result.status_code == 303, result.text
    settled = web_client.get(watch_url).text
    assert "data-inbox-enrichment-" not in settled
    assert "小票已收到，正在识别" not in settled, "上传重定向的旧文案也必须随原单状态一起撤下"
    assert f'data-recognition-task-id="{task_public_id}"' in settled
    assert f'watch={task_public_id}#recognition' not in settled, "保留历史时不留下失效的进度入口"
    with SessionLocal() as db:
        assert db.scalar(select(BackgroundTask.status).where(BackgroundTask.public_id == task_public_id)) == task_status

    if command is web_reject_expense:
        assert web_undo_expense(web_client, expense_id).status_code == 303
        assert "data-inbox-enrichment-" in web_client.get(watch_url).text


@pytest.mark.real_db
def test_web_upload_enrichment_task_presents_real_ocr_success(
    web_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    monkeypatch.setattr(
        enrichment_service,
        "collect_auto_ocr_extractions",
        lambda *_args, **_kwargs: [
            OcrExtraction(
                provider_name="mock",
                ocr_model="test-model",
                result=OcrResult(
                    raw_text="盒马\n交易金额：19.90",
                    confidence=0.98,
                    amount_cents=1990,
                    merchant="盒马",
                ),
            )
        ],
    )

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner&idempotency_key=original-upload&timezone=Asia%2FShanghai",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    page = web_client.get(response.headers["location"])
    assert page.status_code == 200
    assert "data-inbox-enrichment-watch" not in page.text
    assert 'data-enrichment-state="updated"' in page.text
    assert "识别结果已更新，请核对后确认" in page.text

    task_public_id = parse_qs(urlsplit(response.headers["location"]).query)["watch"][0]
    with SessionLocal() as db:
        task = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert task is not None
        assert task.status == "completed"
        result = json.loads(task.result_summary_json or "{}")
        assert result["outcome"] == "updated"
        expense = db.get(Expense, result["expense_id"])
        assert expense is not None
        assert expense.amount_cents == 1990
        assert expense.merchant == "盒马"


@pytest.mark.real_db
def test_web_upload_enrichment_task_presents_provider_failure(
    web_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")

    def fail_ocr(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        enrichment_service,
        "collect_auto_ocr_extractions",
        fail_ocr,
    )

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner&idempotency_key=original-upload",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    page = web_client.get(response.headers["location"])
    assert page.status_code == 200
    assert "data-inbox-enrichment-watch" not in page.text
    assert 'data-enrichment-state="failed"' in page.text
    assert "自动识别失败，账单仍安全保留" in page.text
    band = re.search(r'<div[^>]*data-inbox-enrichment-terminal.*?</div>', page.text, re.S).group()
    open_link = re.search(r'href="([^"]+)"[^>]*>打开账单</a>', band)
    close_link = re.search(r'href="([^"]+)"[^>]*>关闭提示</a>', band)
    assert open_link and close_link, "失败提示必须有真实处理与关闭入口"
    assert web_client.get(unescape(open_link.group(1))).status_code == 200
    close_url = unescape(close_link.group(1))
    assert "watch=" not in close_url
    task_public_id = parse_qs(urlsplit(response.headers["location"]).query)["watch"][0]
    for _ in range(2):
        dismissed = web_client.get(close_url).text
        assert "data-inbox-enrichment-" not in dismissed
        assert f'data-recognition-task-id="{task_public_id}"' in dismissed
