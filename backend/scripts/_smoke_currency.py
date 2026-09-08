"""Choose the smoke installation's currency through its real Desktop Owner entry."""

from __future__ import annotations

import re
import secrets
from uuid import uuid4

import httpx


def choose_smoke_currency(base_url: str, *, session_token: str, ledger_id: str) -> None:
    """Complete explicit setup before the smoke's CNY financial scenarios."""

    with httpx.Client(base_url=base_url, timeout=10) as browser:
        code = browser.post(
            f"/api/ledgers/{ledger_id}/devices/pairing-codes",
            headers={"Authorization": f"Bearer {session_token}"},
            json={},
        )
        assert code.status_code == 201, "smoke Desktop pairing code unavailable"
        attempt_id, attempt_secret = str(uuid4()), secrets.token_urlsafe(32)
        paired = browser.post("/api/auth/pair", json={
            "pairing_code": code.json()["pairing_code"],
            "pairing_attempt_id": attempt_id,
            "pairing_attempt_secret": attempt_secret,
            "device_name": "smoke-desktop",
            "platform": "desktop",
        })
        assert paired.status_code == 200, "smoke Desktop pairing failed"
        activated = browser.post("/api/auth/desktop/activate", json={
            "activation_attempt_id": attempt_id,
            "activation_attempt_secret": attempt_secret,
        })
        assert activated.status_code == 200, "smoke Desktop activation failed"
        browser.headers.update({
            "Authorization": f"Bearer {activated.json()['session_token']}",
            "X-Ticketbox-Desktop-Bridge": "v1",
            "Sec-Fetch-Site": "same-origin",
        })
        before = browser.get("/api/system/runtime-compatibility")
        assert before.status_code == 200
        assert before.json()["capabilities"]["currency"]["home_currency_code"] is None
        page = browser.get("/web/currency-adoption")
        assert page.status_code == 200, "smoke currency choice is unreachable"
        assert not re.search(r'<input\b[^>]*name="home_currency_code"[^>]*\bchecked', page.text)
        fields = {}
        for name in (
            "csrf_token", "currency_contract_version", "expected_state",
            "expected_binding_revision", "evidence_token", "idempotency_key",
        ):
            value = re.search(rf'name="{name}" value="([^"]+)"', page.text)
            assert value is not None, f"smoke currency choice missing {name}"
            fields[name] = value.group(1)
        saved = browser.post("/web/currency-adoption", data={**fields, "home_currency_code": "CNY"})
        assert saved.status_code == 303, "smoke Owner currency confirmation failed"
        after = browser.get("/api/system/runtime-compatibility")
        assert after.status_code == 200
        assert after.json()["capabilities"]["currency"]["home_currency_code"] == "CNY"
        assert after.json()["write_compatibility"] == "compatible"
    print("OK explicit Desktop Owner currency choice")
