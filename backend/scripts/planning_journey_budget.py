"""Actual budget/arrangement/series consumers, sharing the existing journey host."""

from __future__ import annotations

import json
import re

from scripts.planning_journey_android import wait_for

SERIES = "联动房租"
PAGES = {"budget": "/web/budgets", "arrangement": "/web/budget-advise", "series": "/web/recurring"}
CARDS = {"budget": "本月预算剩余", "arrangement": "本月储蓄与备用金", "series": "固定支出"}


def facts(ledger_id):
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import (
        Budget,
        BudgetRevision,
        Expense,
        ExpenseOffsetFact,
        MonthlyArrangement,
        MonthlyArrangementRevision,
        RecurringItem,
        RecurringItemRevision,
        RecurringOccurrence,
        RecurringOccurrenceRevision,
    )

    with SessionLocal() as db:
        def one(model):
            return db.scalar(select(model).where(model.tenant_id == ledger_id))

        def count(model):
            return db.scalar(select(func.count()).select_from(model).where(model.tenant_id == ledger_id))

        budget, arrangement, series = one(Budget), one(MonthlyArrangement), one(RecurringItem)
        expense, occurrence = one(Expense), one(RecurringOccurrence)
        return {
            "budget_amount": budget.total_amount_cents if budget else None,
            "budget_archived": budget.archived_at is not None if budget else None,
            "budget_revisions": count(BudgetRevision),
            "savings": arrangement.savings_target_cents if arrangement else None,
            "buffer": arrangement.reserved_buffer_cents if arrangement else None,
            "arrangement_revisions": count(MonthlyArrangementRevision),
            "series_id": series.public_id if series else None,
            "series_amount": series.baseline_amount_cents if series else None,
            "series_status": series.status if series else None,
            "series_revisions": count(RecurringItemRevision),
            "expenses": count(Expense),
            "expense_id": expense.id if expense else None,
            "expense_status": expense.status if expense else None,
            "expense_amount": expense.amount_cents if expense else None,
            "expense_date": str(expense.accounting_date) if expense else None,
            "offsets": count(ExpenseOffsetFact),
            "linked_expense_id": occurrence.expense_id if occurrence else None,
            "obligation_month": str(occurrence.period_start)[:7] if occurrence else None,
            "occurrence_revisions": count(RecurringOccurrenceRevision),
        }


class BudgetJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.page, self.native, self.fixture = page, native, fixture
        self.evidence, self.base_url = evidence, base_url
        self.ledger_id = fixture.ledger_id
        self.port = int(base_url.rsplit(":", 1)[1])
        self.month = ""

    def facts(self):
        return facts(self.ledger_id)

    def expect_fact(self, key, expected):
        wait_for(lambda: self.facts()[key] == expected, f"The actual consumer did not persist {key}={expected}", 90)

    def goto(self, path, *, page=None):
        target = page or self.page
        join = "&" if "?" in path else "?"
        target.goto(f"{self.base_url}{path}{join}ledger_id={self.ledger_id}&month={self.month}")

    def form(self, action, *, page=None):
        target = page or self.page
        form = target.locator(f'form[method="post"][action="{action}"]')
        if action == "/web/recurring/create" and not form.count():
            target.get_by_role("link", name="添加固定支出", exact=True).click()
        elif action.startswith("/web/recurring/") and action.endswith("/edit") and not form.count():
            target.locator("#item-" + action.split("/")[-2]).get_by_role("link", name="编辑", exact=True).click()
        if not form.is_visible():
            form.locator("xpath=ancestor::details[1]/summary").click()
        return form

    def capture(self, name, *, page=None):
        target = page or self.page
        assert not target.evaluate("document.documentElement.scrollWidth > innerWidth"), "The actual Web page overflows"
        target.screenshot(path=self.evidence / f"web-{name}.png", full_page=True)

    def open_native(self, kind):
        self.native.plan_home()
        self.native.click(CARDS[kind], stable=True)
        if kind == "arrangement":
            wait_for(lambda: self.native.has("月度安排与试算"), "The actual monthly arrangement page did not open")
        if kind == "series":
            wait_for(lambda: self.native.has("固定支出暂时打不开") or any(
                re.fullmatch(r"活跃 \d+", node.attrib.get("text", "")) for node in self.native.tree().iter("node")),
                "The fixed-expense list did not settle")
            if self.native.has("固定支出暂时打不开"):
                self.native.capture("series-read-before-visible-retry")
                log = self.native.adb("logcat", "-d", "-v", "brief")
                # Record only these fixed read-protection messages, never a raw device log.
                reasons = ("固定支出已有更新的读取，请重新读取。", "固定支出已接受修改，请重新读取。",
                    "固定支出操作正在提交，请稍后重新读取。", "固定支出操作已改变，请重新读取。")
                observed = [reason for reason in reasons if reason in log]
                (self.evidence / "series-read-retry-reasons.json").write_text(
                    json.dumps(observed, ensure_ascii=False), encoding="utf-8")
                raise AssertionError("The actual fixed-expense consumer failed its current read; see the retained diagnostic")
            self.native.click_counted_tab("活跃")

    def login(self):
        page = self.page
        page.goto(f"{self.base_url}/web/auth/local?next=/web/budgets")
        page.locator(f'input[name="ledger_id"][value="{self.ledger_id}"]').check()
        page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
        page.wait_for_url("**/web/budgets*")
        self.month = self.form("/web/budgets/save").locator('[name="month"]').input_value()

    def create(self):
        self.login()
        form = self.form("/web/budgets/save")
        form.locator('[name="total_amount_yuan"]').fill("10000.00")
        form.locator("[data-budget-submit]").click()
        self.expect_fact("budget_amount", 1000000)
        self.goto(PAGES["arrangement"])
        form = self.form("/web/budget-advise")
        form.locator('[name="savings_target_yuan"]').fill("1000.00")
        form.locator('[name="reserved_buffer_yuan"]').fill("500.00")
        form.get_by_role("button", name="试算，不保存", exact=True).click()
        self.page.wait_for_load_state("networkidle")
        assert self.facts()["arrangement_revisions"] == 0, "Trial wrote a saved arrangement"
        form.locator("[data-arrangement-submit]").click()
        self.expect_fact("savings", 100000)
        self.goto(PAGES["series"])
        form = self.form("/web/recurring/create")
        form.locator('[name="merchant"]').fill(SERIES)
        form.locator('[name="baseline_amount_yuan"]').fill("1200.00")
        form.locator('[name="next_expected_date"]').fill(self.month + "-15")
        form.locator("[data-recurring-submit]").click()
        self.expect_fact("series_amount", 120000)
        assert self.facts()["expenses"] == 0, "Planning created a payment"
        self.native.bind(self.fixture.pairing_code, self.port)

    def native_edits(self):
        self.open_native("budget")
        self.native.reveal_any("调整本月预算")
        self.native.click("调整本月预算")
        self.native.reveal_any("月度总预算")
        self.native.fill("11000.00", previous=r"10,?000(?:\.00)?")
        self.native.click("保存预算")
        self.expect_fact("budget_amount", 1100000)
        self.open_native("series")
        self.native.reveal_any(SERIES)
        self.native.capture("series-from-web-paper")
        self.native.click(SERIES)
        self.native.fill("1300.00", previous=r"1,?200(?:\.00)?")
        self.native.click("保存")
        self.expect_fact("series_amount", 130000)

    def history(self, *, offline=False):
        suffix = "offline-restart" if offline else "online"
        self.open_native("budget")
        self.native.reveal_any("预算修改记录", toward_start=True)
        self.native.click("预算修改记录")
        if offline:
            self.native.reveal_any("本机保留")
        self.native.reveal_any("建立预算")
        self.native.capture("budget-history-" + suffix)
        self.native.back()
        self.open_native("arrangement")
        self.native.click("查看修改历史")
        if offline:
            self.native.reveal_any("离线缓存")
        self.native.reveal_any("v1")
        self.native.capture("arrangement-history-" + suffix)
        self.open_native("series")
        self.native.click("定义历史")
        if offline:
            self.native.reveal_any("离线保存")
        self.native.reveal_any("1,200", "1200")
        self.native.capture("series-history-" + suffix)
        self.native.back()

    def appearances(self):
        page = self.page
        for theme in ("paper", "midnight"):
            page.set_viewport_size({"width": 1280, "height": 960})
            self.goto(PAGES["budget"])
            page.locator("#appearance > summary").click()
            page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
            page.locator("#appearance > summary").click()
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 960})
                for kind, path in PAGES.items():
                    self.goto(path)
                    assert page.locator("html").get_attribute("data-theme") == theme
                    self.capture(f"{kind}-{width}-{theme}")
        self.native.plan_home()
        self.native.click("打开账户与设置")
        self.native.click("通知与外观")
        self.native.click("外观与主题")
        self.native.click("玄夜")
        for kind, values in (("budget", ("11,500", "11500")), ("arrangement", ("1,150", "1150")),
                             ("series", ("1,450", "1450"))):
            self.open_native(kind)
            self.native.reveal_any(*values)
            self.native.capture(kind + "-midnight")

    def run(self):
        from scripts.planning_journey_budget_payment import payment_chain
        from scripts.planning_journey_budget_recovery import BudgetRecovery
        from scripts.planning_journey_budget_roles import roles

        self.create()
        self.native_edits()
        BudgetRecovery(self).run()
        payment_chain(self)
        roles(self)
        self.appearances()
        result = self.facts()
        assert result["budget_amount"] == 1150000 and result["savings"] == 115000
        assert result["series_amount"] == 145000 and result["series_status"] == "active"
        assert not result["budget_archived"] and result["expenses"] == result["offsets"] == 1
        result["verified_leg"] = "Actual Web/native budget, arrangement and series edits; trial without save; offline original resumption; stale conflict; lost-reply replay; both recycle bins; retained histories; cross-month Expense confirmation and explicit occurrence association; reversal and restored reservation; member/viewer and both themes"
        return result
