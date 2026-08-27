from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from tests._infra.assets import PNG_BYTES


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_web_pending_upload_creates_real_pending_expense(
    web_client: TestClient,
) -> None:
    response = web_client.post(
        "/web/pending/upload",
        data={"ledger_id": "owner", "timezone": "Asia/Shanghai"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/web/pending?")
    assert "ledger_id=owner" in response.headers["location"]

    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense)
            .where(Expense.tenant_id == "owner", Expense.source == "网页上传")
            .order_by(Expense.id.desc())
            .limit(1)
        )
        assert expense is not None
        assert expense.status == "pending"
        assert expense.image_path is not None
        assert expense.image_hash


def test_web_pending_upload_rejects_viewer_before_saving(
    web_client: TestClient,
) -> None:
    _demote_owner_ledger_to_viewer()

    response = web_client.post(
        "/web/pending/upload",
        data={"ledger_id": "owner", "timezone": "Asia/Shanghai"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(Expense.id).where(
                    Expense.tenant_id == "owner",
                    Expense.source == "网页上传",
                )
            )
            is None
        )


def test_retired_inbox_surfaces_and_dashboard_owner_are_gone(
    web_client: TestClient,
) -> None:
    assert web_client.get("/web/tasks").status_code == 404
    assert web_client.get("/web/dashboard/data").status_code == 404

    app_root = Path(__file__).resolve().parents[1] / "app"
    assert not (app_root / "templates" / "web" / "tasks.html").exists()
    assert not (app_root / "templates" / "web" / "dashboard.html").exists()
    assert not (app_root / "static" / "web" / "desktop" / "dashboard.js").exists()


def test_retired_dashboard_runtime_owners_are_physically_gone() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"

    assert not (app_root / "static" / "web" / "pages" / "dashboard.css").exists()
    assert (app_root / "static" / "web" / "components" / "responsive-layout.css").exists()

    desktop_boot = (app_root / "static" / "web" / "desktop.js").read_text(encoding="utf-8")
    assert "initDashboard" not in desktop_boot
    assert "initSparks" not in desktop_boot

    desktop_core = (app_root / "static" / "web" / "desktop" / "core.js").read_text(encoding="utf-8")
    assert "dashboardUrl" not in desktop_core

    insights_css = (
        app_root / "static" / "web" / "product" / "domains" / "insights.css"
    ).read_text(encoding="utf-8")
    assert "data-dashboard-state" not in insights_css

    inbox_css = (
        app_root / "static" / "web" / "product" / "domains" / "inbox.css"
    ).read_text(encoding="utf-8")
    assert ".task-" not in inbox_css

    mutation_ledger = (
        app_root.parent / "scripts" / "_mutate_token_ledger.py"
    ).read_text(encoding="utf-8")
    assert 'POST /web/tasks/{public_id}/cancel' not in mutation_ledger
