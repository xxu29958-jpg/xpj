"""DEV ONLY: write a small, coherent set of sample records through the product's own JSON API.

Usage, against a locally running development server:

    python scripts/dev_sample_data.py --base-url http://127.0.0.1:8000 --pairing-code <code>

The script is an ordinary client. It pairs as one new device with a pairing code you issue from
the Owner console, negotiates the current protocol headers from the runtime-compatibility endpoint,
and creates everything through the same endpoints the apps use. It does not open the database,
does not adopt or change the installation currency, and keeps the session token in memory only.

Amounts are minor units of the installation's home currency; with a two-decimal currency they
reproduce the design samples (2,460 confirmed this month, 2,740 last month, a 4,000 budget,
debts of 1,200 - 300 = 900, 260 and 500). It refuses to run when the ledger already has confirmed
expenses unless ``--append`` is given, and it only talks to a loopback address.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from datetime import date, datetime, timedelta
from urllib import error, parse, request


class Client:
    """A minimal JSON client that carries the negotiated product headers."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {}

    def call(self, method: str, path: str, body: object | None = None, *, key: bool = False, raw: bytes | None = None,
             content_type: str = "application/json") -> tuple[int, object]:
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = uuid.uuid4().hex
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        if data is not None:
            headers["Content-Type"] = content_type
        req = request.Request(self.base_url + path, data=data, method=method, headers=headers)  # noqa: S310
        try:
            with request.urlopen(req, timeout=30) as response:  # noqa: S310
                text = response.read().decode("utf-8")
                return response.status, json.loads(text) if text else None
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(text)
            except ValueError:
                return exc.code, text[:200]

    def post(self, path: str, body: object, *, label: str) -> dict | None:
        status, payload = self.call("POST", path, body, key=True)
        if status not in (200, 201):
            print(f"  skipped {label}: {status} {_reason(payload)}")
            return None
        print(f"  {label}")
        return payload if isinstance(payload, dict) else {}


def _reason(payload: object) -> str:
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("message") or "")[:120]
    return str(payload)[:120]


def connect(base_url: str, pairing_code: str) -> tuple[Client, str]:
    client = Client(base_url)
    status, paired = client.call("POST", "/api/auth/pair", {
        "pairing_code": pairing_code, "pairing_attempt_id": str(uuid.uuid4()),
        "pairing_attempt_secret": secrets.token_urlsafe(32), "device_name": "示例数据脚本", "platform": "android"})
    if status != 200 or not isinstance(paired, dict):
        raise SystemExit(f"Pairing failed ({status}): {_reason(paired)}. Issue a fresh pairing code in the Owner console.")
    client.headers = {"Authorization": "Bearer " + paired["session_token"]}
    status, snapshot = client.call("GET", "/api/system/runtime-compatibility")
    if status != 200 or not isinstance(snapshot, dict):
        raise SystemExit(f"Could not read runtime compatibility ({status}).")
    currency = snapshot["capabilities"]["currency"]
    if not currency.get("request_binding") or not currency.get("home_currency_code"):
        raise SystemExit("The installation currency is not adopted yet. Adopt it in the product first; this script never does.")
    client.headers[snapshot["api_version_header"]] = snapshot["api_version"]
    client.headers[currency["request_binding_header"]] = currency["request_binding"]
    return client, currency["home_currency_code"]


def _moment(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0).astimezone().isoformat()


def add_expenses(client: Client, currency: str, today: date) -> None:
    first = today.replace(day=1)
    last_month = (first - timedelta(days=1)).replace(day=1)
    def this_month(offset: int) -> date:
        return min(first + timedelta(days=offset), today)

    # A manual entry is a confirmed fact as soon as it is recorded; nothing here lands in the inbox.
    samples = [
        ("房租", "住房", 114000, last_month, 12), ("家常餐饮", "餐饮", 80000, last_month + timedelta(days=11), 12),
        ("换季衣物", "购物", 50000, last_month + timedelta(days=17), 12), ("地铁月票", "交通", 30000, last_month + timedelta(days=4), 12),
        ("房租", "住房", 114000, this_month(0), 9), ("家庭聚餐", "餐饮", 60000, this_month(1), 19),
        ("超市采购", "购物", 48000, this_month(1), 10), ("交通充值", "交通", 24000, this_month(2), 12),
    ]
    for merchant, category, amount, day, hour in samples:
        status, expense = client.call("POST", "/api/expenses/manual", {
            "client_ref": "sample-" + uuid.uuid4().hex[:20], "merchant": merchant, "category": category,
            "home_currency_code": currency, "amount_cents": amount, "expense_time": _moment(day, hour)})
        print(f"  expense {merchant}" if status == 200 else f"  skipped expense {merchant}: {status} {_reason(expense)}")


def add_plans(client: Client, currency: str, today: date) -> None:
    month = today.strftime("%Y-%m")
    status, payload = client.call("PUT", f"/api/budgets/monthly/{month}", {
        "home_currency_code": currency, "expected_row_version": None, "total_amount_cents": 400000,
        "category_budgets": [{"category": "住房", "amount_cents": 160000}, {"category": "餐饮", "amount_cents": 90000}]}, key=True)
    print("  budget" if status in (200, 201) else f"  skipped budget: {status} {_reason(payload)}")
    client.post("/api/goals", {"name": "餐饮控制", "goal_type": "spending_limit", "period": "monthly", "month": month,
                               "category": "餐饮", "target_amount_cents": 90000, "home_currency_code": currency}, label="spending goal")
    next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    for merchant, amount, due in (("房租", 114000, next_month), ("宽带", 9900, today + timedelta(days=3))):
        client.post("/api/recurring/items", {"home_currency_code": currency, "merchant": merchant, "baseline_amount_cents": amount,
                                             "next_expected_date": due.isoformat()}, label=f"recurring {merchant}")
    client.post("/api/income-plans", {"intent_month": month, "home_currency_code": currency, "label": "工资", "source_type": "salary",
                                      "frequency": "monthly", "amount_cents": 700000, "pay_day": 10}, label="income plan")


def add_obligations(client: Client, currency: str) -> None:
    def debt(label: str, direction: str, amount: int, **extra: object) -> dict | None:
        return client.post("/api/debts", {"direction": direction, "home_currency_code": currency, "counterparty_type": "external",
                                          "counterparty_label": label, "principal_amount_cents": amount, **extra}, label=f"debt {label}")

    first = debt("家人甲", "i_owe", 120000, note="周转")
    second = debt("朋友丙", "i_owe", 26000)
    debt("朋友乙", "owed_to_me", 50000)
    debt("信用卡分期", "i_owe", 360000, debt_kind="installment", installment_count=12, installment_period_months=1)
    if first:
        client.post(f"/api/debts/{first['public_id']}/repayments", {"amount_cents": 30000, "expected_row_version": first["row_version"]},
                    label="repayment 300")
    linked = [item["public_id"] for item in (first, second) if item]
    if linked:
        client.post("/api/goals", {"name": "年底前还清", "goal_type": "debt_repayment", "debt_public_ids": linked}, label="debt goal")
    client.post("/api/repayment-drafts", {"source": "alipay", "original_currency": currency, "original_amount": "300.00",
                                          "merchant_label": "家人甲"}, label="repayment capture (pending)")


def add_family(client: Client) -> None:
    for role, name in (("member", "家人甲"), ("viewer", "家人乙")):
        invitation = client.post("/api/ledgers/owner/invitations", {"role": role, "note": name, "ttl_days": 7}, label=f"invitation {name}")
        if not invitation:
            continue
        status, payload = Client(client.base_url).call("POST", "/api/invitations/accept", {
            "invite_token": invitation["invite_token"], "account_name": name, "device_name": name + "的手机", "platform": "android",
            "enrollment_attempt_id": str(uuid.uuid4()), "enrollment_attempt_secret": secrets.token_urlsafe(32)})
        print(f"  {name} joined as {role}" if status == 200 else f"  skipped join {name}: {status} {_reason(payload)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write development sample data through the product JSON API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--pairing-code", required=True, help="a fresh pairing code issued from the Owner console")
    parser.add_argument("--append", action="store_true", help="write even when the ledger already has confirmed expenses")
    args = parser.parse_args()
    if parse.urlsplit(args.base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("This script only writes to a development server on a loopback address.")
    client, currency = connect(args.base_url, args.pairing_code)
    status, confirmed = client.call("GET", "/api/expenses/confirmed?page_size=1")
    existing = (confirmed.get("total") or len(confirmed.get("items", []))) if isinstance(confirmed, dict) else 0
    if status == 200 and existing and not args.append:
        raise SystemExit("This ledger already has confirmed expenses. Use --append to add the samples anyway.")
    today = date.today()
    for title, step in (("Expenses", lambda: add_expenses(client, currency, today)), ("Plans", lambda: add_plans(client, currency, today)),
                        ("Obligations", lambda: add_obligations(client, currency)), ("Family", lambda: add_family(client))):
        print(title)
        step()
    return 0


if __name__ == "__main__":
    sys.exit(main())
