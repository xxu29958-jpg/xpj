from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = role
        db.commit()


def test_dashboard_cards_defaults_update_and_ledger_scope(client: TestClient, *, identity) -> None:
    default_android = client.get(
        "/api/dashboard/cards?surface=android",
        headers=identity.app_headers,
    )
    assert default_android.status_code == 200, default_android.json()
    android_payload = default_android.json()
    assert android_payload["surface"] == "android"
    assert [item["key"] for item in android_payload["items"]][:3] == [
        "monthly_spend",
        "budget",
        "reports",
    ]

    updated_web = client.put(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
        json={
            "cards": [
                {"key": "goals", "visible": True, "position": 0},
                {"key": "reports", "visible": False, "position": 1},
                {"key": "monthly_spend", "visible": True, "position": 2},
            ]
        },
    )
    assert updated_web.status_code == 200, updated_web.json()
    web_items = updated_web.json()["items"]
    assert [item["key"] for item in web_items[:3]] == [
        "goals",
        "reports",
        "monthly_spend",
    ]
    assert web_items[1]["visible"] is False

    updated_web_without_reports = client.put(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
        json={
            "cards": [
                {"key": "goals", "visible": True, "position": 0},
                {"key": "monthly_spend", "visible": True, "position": 1},
            ]
        },
    )
    assert updated_web_without_reports.status_code == 200, updated_web_without_reports.json()
    web_items_after_omission = updated_web_without_reports.json()["items"]
    web_keys_after_omission = [item["key"] for item in web_items_after_omission]
    reports_after_omission = next(item for item in web_items_after_omission if item["key"] == "reports")
    assert web_keys_after_omission[:2] == ["goals", "monthly_spend"]
    assert web_keys_after_omission.index("reports") > web_keys_after_omission.index("monthly_spend")
    assert reports_after_omission["visible"] is True
    assert reports_after_omission["position"] > web_items_after_omission[1]["position"]

    android_after_web_update = client.get(
        "/api/dashboard/cards?surface=android",
        headers=identity.app_headers,
    )
    assert android_after_web_update.status_code == 200, android_after_web_update.json()
    assert [item["key"] for item in android_after_web_update.json()["items"]][:3] == [
        "monthly_spend",
        "budget",
        "reports",
    ]

    gray_web = client.get(
        "/api/dashboard/cards?surface=web",
        headers=identity.gray_app_headers,
    )
    assert gray_web.status_code == 200, gray_web.json()
    assert [item["key"] for item in gray_web.json()["items"]][:3] == [
        "monthly_spend",
        "budget",
        "reports",
    ]
    assert all(item["visible"] for item in gray_web.json()["items"])


def test_dashboard_cards_validation_and_viewer_write_guard(client: TestClient, *, identity) -> None:
    invalid_surface = client.get(
        "/api/dashboard/cards?surface=owner",
        headers=identity.app_headers,
    )
    assert invalid_surface.status_code == 422
    assert invalid_surface.json()["error"] == "invalid_request"

    unknown = client.put(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
        json={"cards": [{"key": "net_worth", "visible": True, "position": 0}]},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"] == "invalid_request"

    duplicate = client.put(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
        json={
            "cards": [
                {"key": "reports", "visible": True, "position": 0},
                {"key": "reports", "visible": False, "position": 1},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"] == "invalid_request"

    duplicate_position = client.put(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
        json={
            "cards": [
                {"key": "reports", "visible": True, "position": 0},
                {"key": "goals", "visible": True, "position": 0},
            ]
        },
    )
    assert duplicate_position.status_code == 422
    assert duplicate_position.json()["error"] == "invalid_request"

    _set_owner_ledger_role("viewer")
    viewer_read = client.get(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
    )
    assert viewer_read.status_code == 200, viewer_read.json()

    viewer_write = client.put(
        "/api/dashboard/cards?surface=web",
        headers=identity.app_headers,
        json={"cards": [{"key": "reports", "visible": False, "position": 0}]},
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["error"] == "permission_denied"
