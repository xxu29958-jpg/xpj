"""Web reader entry uses the same authorized history as the app API."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests.test_web_budgets import _save_budget
from tests.test_web_budgets import web_client as web_client


def test_history_from_budget_page_preserves_viewer_access_and_selected_ledger(web_client):
    _save_budget(web_client)
    with SessionLocal.begin() as db:
        db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner")).role = "viewer"
    page = web_client.get("/web/budgets", params={"ledger_id": "owner", "month": "2026-05"})
    assert page.status_code == 200 and "/web/budgets/history?" in page.text
    history = web_client.get("/web/budgets/history", params={"ledger_id": "owner", "month": "2026-05"})
    assert history.status_code == 200, history.text
    assert "建立预算" in history.text and "¥1,000.00" in history.text
    assert "餐饮" in history.text and 'action="/web/budgets/save"' not in history.text
    other = web_client.get("/web/budgets/history", params={"ledger_id": "tester_1", "month": "2026-05"})
    assert other.status_code == 200 and "这个月还没有保存过预算记录" in other.text
    assert "¥1,000.00" not in other.text
