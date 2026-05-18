from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, LedgerMember
from app.services.identity_service import hash_secret
from app.services.time_service import now_utc


def _same_name_member_token(label: str) -> str:
    token = f"same-name-pref-token-{label}"
    now = now_utc()
    with SessionLocal() as db:
        account = Account(display_name="Same Name", created_at=now)
        db.add(account)
        db.flush()
        device = Device(
            account_id=account.id,
            device_name=f"same-name-device-{label}",
            platform="android",
            created_at=now,
        )
        db.add(device)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id="owner",
                account_id=account.id,
                role="member",
                created_at=now,
            )
        )
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id="owner",
                scope="app",
                created_at=now,
            )
        )
        db.commit()
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ui_preferences_are_keyed_by_account_id_not_display_name(client: TestClient) -> None:
    token_a = _same_name_member_token("a")
    token_b = _same_name_member_token("b")

    first = client.put("/api/me/ui-preferences", headers=_headers(token_a), json={"theme": "mono"})
    assert first.status_code == 200, first.json()
    second = client.put("/api/me/ui-preferences", headers=_headers(token_b), json={"theme": "midnight"})
    assert second.status_code == 200, second.json()

    read_a = client.get("/api/me/ui-preferences", headers=_headers(token_a))
    read_b = client.get("/api/me/ui-preferences", headers=_headers(token_b))

    assert read_a.status_code == 200, read_a.json()
    assert read_b.status_code == 200, read_b.json()
    assert read_a.json()["theme"] == "mono"
    assert read_b.json()["theme"] == "midnight"
