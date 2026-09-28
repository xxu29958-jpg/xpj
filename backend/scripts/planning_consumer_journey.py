"""A real browser and Android app share one ephemeral PostgreSQL installation.

The fixture creates only its installation identity and initial currency adoption.
All income/goal commands must come from the actual product consumers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from scripts.planning_journey_android import PlanningAndroid, wait_for
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import dedicated_test_database_lease

PORT = 18880
BASE_URL = f"http://127.0.0.1:{PORT}"


def _facts(ledger_id: str) -> dict:
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import Budget, Expense, Goal, IncomePlanRevision, MonthlyIncomePlan

    with SessionLocal() as db:
        income = db.scalar(select(MonthlyIncomePlan).where(MonthlyIncomePlan.tenant_id == ledger_id))
        goal = db.scalar(select(Goal).where(Goal.tenant_id == ledger_id))
        return {
            "income_id": income.public_id if income else None,
            "income_amount": income.amount_cents if income else None,
            "income_status": income.status if income else None,
            "income_revisions": db.scalar(select(func.count()).select_from(IncomePlanRevision)),
            "goal_id": goal.public_id if goal else None,
            "goal_amount": goal.target_amount_cents if goal else None,
            "goal_status": goal.status if goal else None,
            "expenses": db.scalar(select(func.count()).select_from(Expense)),
            "budgets": db.scalar(select(func.count()).select_from(Budget)),
        }


def _seed():
    from app.database import SessionLocal, init_db
    from app.services.identity_service import bootstrap_installation_owner
    from tests._infra.currency import activate_test_currency_authority

    init_db()
    with SessionLocal() as db:
        fixture = bootstrap_installation_owner(db, operation_id="planning-consumer-journey",
            installation_id="planning-consumer-journey", bootstrap_secret=secrets.token_urlsafe(32),
            account_name="联动验证账户", ledger_name="收入与目标验证账本", device_name="隔离浏览器")
        activate_test_currency_authority(db, "CNY")
        db.commit()
        return fixture


def _ready() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _form(page, action: str):
    form = page.locator(f'form[action="{action}"]')
    if not form.is_visible():
        form.locator("xpath=ancestor::details").locator("summary").click()
    return form


def _web_capture(page, evidence: Path, name: str):
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "The actual Web page overflows"
    page.screenshot(path=evidence / f"web-{name}.png", full_page=True)


def _journey(page, native: PlanningAndroid, fixture, evidence: Path):
    page.goto(f"{BASE_URL}/web/auth/local?next=/web/income-plans")
    page.locator(f'input[name="ledger_id"][value="{fixture.ledger_id}"]').check()
    page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
    page.wait_for_url("**/web/income-plans*")
    income_form = _form(page, "/web/income-plans/create")
    income_form.locator('[name="label"]').fill("联动工资")
    income_form.locator('[name="amount_yuan"]').fill("5000.00")
    month = income_form.locator('[name="intent_month"]').input_value()
    income_form.locator('button[type="submit"]').click()
    wait_for(lambda: _facts(fixture.ledger_id)["income_amount"] == 500000, "Web income was not committed")

    page.goto(f"{BASE_URL}/web/goals?month={month}")
    goal_form = _form(page, "/web/goals/create")
    goal_form.locator('[name="name"]').fill("联动消费提醒")
    goal_form.locator('[name="target_amount_yuan"]').fill("2000.00")
    goal_form.locator('button[type="submit"]').click()
    wait_for(lambda: _facts(fixture.ledger_id)["goal_amount"] == 200000, "Web goal was not committed")
    native.bind(fixture.pairing_code, PORT)
    native.open_income()
    native.capture("income-from-web")
    native.click("联动工资")
    native.fill("6000.00", previous=r"5,?000(?:\.00)?")
    native.click("保存")
    wait_for(lambda: _facts(fixture.ledger_id)["income_amount"] == 600000, "The native original submission did not reach PostgreSQL", 90)

    facts = _facts(fixture.ledger_id)
    page.goto(f"{BASE_URL}/web/income-plans/{facts['income_id']}/history?ledger_id={fixture.ledger_id}")
    assert "5000.00" in page.inner_text("main") and "6000.00" in page.inner_text("main")
    _web_capture(page, evidence, "income-history-after-native-edit")
    page.goto(f"{BASE_URL}/web/goals/{facts['goal_id']}/edit?ledger_id={fixture.ledger_id}")
    goal_form = _form(page, f"/web/goals/{facts['goal_id']}/edit")
    goal_form.locator('[name="target_amount_yuan"]').fill("2200.00")
    goal_form.locator('button[type="submit"]').click()
    wait_for(lambda: _facts(fixture.ledger_id)["goal_amount"] == 220000, "The Web goal edit did not commit")

    native.plan_home()
    native.click("消费目标")
    wait_for(lambda: native.has("联动消费提醒"), "The native goal list did not read the Web-created target")
    native.click("联动消费提醒")
    wait_for(lambda: native.has("2,200") or native.has("2200"), "The native detail did not show the Web-edited amount")
    native.capture("goal-after-web-edit")
    native.click("定义历史")
    native.capture("goal-history")
    native.back()

    for width in (1280, 390):
        page.set_viewport_size({"width": width, "height": 960})
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            for name, path in (("income", "/web/income-plans"), ("goals", f"/web/goals?month={month}")):
                page.goto(BASE_URL + path)
                _web_capture(page, evidence, f"{name}-{width}-{scheme}")
    result = _facts(fixture.ledger_id)
    assert result["expenses"] == result["budgets"] == 0, "A prediction or reminder created financial facts"
    assert result["income_amount"] == 600000 and result["goal_amount"] == 220000
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Run this sustained PostgreSQL/native journey in the isolated cloud job")
    args.evidence.mkdir(parents=True, exist_ok=True)
    native = PlanningAndroid(args.serial, args.evidence)
    database_url = os.environ["SMOKE_DATABASE_URL"]
    os.environ["DATABASE_URL"] = database_url
    os.environ["XPJ_EXTRA_LOOPBACK_HOSTS"] = f"127.0.0.1:{PORT}"
    for key in ("UPLOAD_TOKEN", "APP_TOKEN", "ADMIN_TOKEN"):
        os.environ[key] = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="planning-consumers-", dir=os.environ["RUNNER_TEMP"]) as data:
        os.environ["TICKETBOX_DATA_DIR"] = data
        os.environ["UPLOAD_DIR"] = str(Path(data) / "uploads")
        with dedicated_test_database_lease(database_url, expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
            reset=True, cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"], passfile=os.environ["PGPASSFILE"]):
            fixture = _seed()
            native.adb("install", "-r", str(args.apk.resolve()))
            native.adb("shell", "pm", "grant", "com.ticketbox", "android.permission.POST_NOTIFICATIONS")
            with (args.evidence / "server.log").open("w", encoding="utf-8") as server_log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                    "--port", str(PORT), "--no-access-log"], stdout=server_log, stderr=subprocess.STDOUT)
                try:
                    wait_for(_ready, "The real backend did not become ready")
                    from playwright.sync_api import sync_playwright

                    with sync_playwright() as driver:
                        browser = driver.chromium.launch()
                        page = browser.new_page(viewport={"width": 1280, "height": 960})
                        result = _journey(page, native, fixture, args.evidence)
                        browser.close()
                    result["checkout_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
                    result["source_sha"] = os.environ["TICKETBOX_JOURNEY_SOURCE_SHA"]
                    result["apk_sha256"] = hashlib.sha256(args.apk.read_bytes()).hexdigest()
                    result["verified_leg"] = "Web creation, native income edit, Web history and goal edit, native goal history"
                    (args.evidence / "business-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                    print("The Web/native creation, cross-client edit and history leg completed")
                except Exception:
                    try:
                        native.capture("failure", redact=fixture.pairing_code)
                    except Exception:
                        print("Native failure capture was unavailable")
                    raise
                finally:
                    server.terminate()
                    server.wait(timeout=20)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
