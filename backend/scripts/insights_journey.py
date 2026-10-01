"""Follow report scopes into actual facts, correct them, and return to the report."""

from urllib.parse import parse_qs, urlencode, urlsplit

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, ExpenseRevision
from app.services.stats_service import monthly_stats
from scripts.planning_journey_android import wait_for


class InsightsJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.page, self.native, self.fixture = page, native, fixture
        self.evidence, self.base_url = evidence, base_url

    def facts(self):
        with SessionLocal() as db:
            rows = db.scalars(select(Expense).where(Expense.tenant_id == self.fixture.ledger_id)
                .order_by(Expense.id)).all()
            if not rows:
                return {"expenses": []}
            month = rows[0].accounting_date.strftime("%Y-%m")
            revisions = db.scalars(select(ExpenseRevision).where(ExpenseRevision.expense_id.in_(
                [row.id for row in rows])).order_by(ExpenseRevision.id)).all()
            return {"month": month,
                "expenses": [{"id": row.id, "merchant": row.merchant, "amount": row.amount_cents,
                    "category": row.category, "tags": row.tags, "status": row.status} for row in rows],
                "tagged_stats": monthly_stats(db, month, self.fixture.ledger_id, tag="Travel"),
                "all_stats": monthly_stats(db, month, self.fixture.ledger_id),
                "revision_reasons": [row.reason for row in revisions]}

    def goto(self, path):
        response = self.page.goto(self.base_url + path + ("&" if "?" in path else "?") +
            urlencode({"ledger_id": self.fixture.ledger_id}))
        assert response.ok, f"The actual insights consumer failed: {path} ({response.status})"

    def capture(self, name):
        assert not self.page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Insights overflows"
        self.page.screenshot(path=self.evidence / f"web-insights-{name}.png", full_page=True)

    def prepare(self):
        page = self.page
        page.goto(self.base_url + "/web/auth/local?next=/web/expenses/new")
        page.locator(f'input[name="ledger_id"][value="{self.fixture.ledger_id}"]').check()
        page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
        page.wait_for_url("**/web/expenses/new*")
        for merchant, amount, category, tag in (
            ("TaggedMeal", "12.00", "餐饮", "Travel"),
            ("OrdinaryMeal", "8.00", "餐饮", "Home"),
            ("TaggedRide", "4.00", "交通", "Travel"),
        ):
            self.goto("/web/expenses/new")
            form = page.locator('form[action="/web/expenses/new"]')
            form.locator('[name="amount_major"]').fill(amount)
            if not form.locator('[name="merchant"]').is_visible():
                form.locator("details.manual-expense-options > summary").click()
            form.locator('[name="merchant"]').fill(merchant)
            form.locator('[name="category"]').fill(category)
            form.get_by_role("button", name="记下这笔支出", exact=True).click()
            wait_for(lambda: any(row["merchant"] == merchant for row in self.facts()["expenses"]),
                "The actual manual entry did not create the report fact")
            row = next(row for row in self.facts()["expenses"] if row["merchant"] == merchant)
            self.goto(f'/web/expenses/{row["id"]}/correct')
            form = page.locator(f'form[action="/web/expenses/{row["id"]}/corrections"]')
            form.locator('[name="tags"]').fill(tag)
            form.locator('[name="reason"]').fill("ReportScope")
            form.locator("[data-correction-submit]").click()
            wait_for(lambda: any(row["merchant"] == merchant and row["tags"] == tag
                for row in self.facts()["expenses"]), "The actual correction did not retain the tag")
        state = self.facts()
        assert state["tagged_stats"]["total_amount_cents"] == 1600
        assert state["all_stats"]["total_amount_cents"] == 2400
        self.native.bind(self.fixture.pairing_code, urlsplit(self.base_url).port)

    def tagged_drill_and_return(self):
        native = self.native
        native.domain_home("流水")
        native.reveal_any("TaggedMeal")
        # The report can read a peer's change while the existing ledger tab still has its old projection.
        expense_id = self.facts()["expenses"][0]["id"]
        self.goto(f"/web/expenses/{expense_id}/correct")
        form = self.page.locator(f'form[action="/web/expenses/{expense_id}/corrections"]')
        form.locator('[name="amount_yuan"]').fill("13.00")
        form.locator('[name="reason"]').fill("PeerBeforeDrill")
        form.locator("[data-correction-submit]").click()
        wait_for(lambda: self.facts()["expenses"][0]["amount"] == 1300, "The peer change did not commit")
        native.domain_home("洞察")
        native.click("全部标签")
        native.click("#Travel")
        native.reveal_any("17.00")
        native.click("构成")
        native.reveal_any("餐饮")
        native.capture("insights-tagged-composition")
        native.click("餐饮")
        wait_for(lambda: native.has("TaggedMeal"), "The selected category did not open its actual fact")
        native.capture("insights-tagged-drill")
        assert not native.has("OrdinaryMeal"), "Category drill discarded the report tag and included an unrelated bill"
        assert not native.has("TaggedRide"), "Category drill discarded the selected category"
        wait_for(lambda: native.has("13.00"), "The drill kept an older ledger snapshot than its source report")
        native.click("TaggedMeal")
        native.click("更正这笔账单")
        native.fill("DrillAmount", label="更正原因（必填）")
        native.reveal_any("13.00")
        native.fill("15.00", previous="13.00")
        native.click("保存更正")
        wait_for(lambda: self.facts()["expenses"][0]["amount"] == 1500,
            "Correction from the drilled fact did not reach the existing fact owner")
        native.domain_home("洞察")
        assert native.has("#Travel"), "Returning to insights discarded the selected tag"
        native.click("概览")
        native.reveal_any("19.00")
        native.capture("insights-returned-after-correction")
        # An unfiltered report replaces the previous drill tag as well.
        native.click("#Travel")
        native.click("全部标签")
        native.click("构成")
        native.click("餐饮")
        native.reveal_any("TaggedMeal")
        assert native.has("OrdinaryMeal"), "An unfiltered category drill retained an earlier report tag"
        native.capture("insights-unfiltered-drill")

    def web_report_return(self):
        page = self.page
        state = self.facts()
        query = {"month": state["month"], "home_currency_code": "CNY", "granularity": "week",
            "ranking_metric": "count", "merchant_category": "餐饮"}
        self.goto("/web/reports?" + urlencode(query))
        path = f'/web/expenses/{state["expenses"][0]["id"]}'
        page.locator(f'a[href^="{path}/edit?"]').first.click()
        page.locator(f'a[href^="{path}/correct?"]').first.click()
        form = page.locator(f'form[action="{path}/corrections"]')
        form.locator('[name="merchant"]').fill("ReviewedMeal")
        form.locator('[name="reason"]').fill("ReportReturn")
        form.locator("[data-correction-submit]").click()
        wait_for(lambda: self.facts()["expenses"][0]["merchant"] == "ReviewedMeal",
            "The Web report fact correction did not commit")
        page.get_by_role("link", name="返回原月份月报", exact=True).click()
        returned = parse_qs(urlsplit(page.url).query)
        assert all(returned.get(key) == [value] for key, value in query.items()), returned
        assert "ReviewedMeal" in page.inner_text("main"), "The returned report did not reread the corrected fact"
        self.capture("returned-original-report-scope")
        for theme in ("paper", "midnight"):
            page.locator("#appearance > summary").click()
            page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            wait_for(lambda: page.locator("html").get_attribute("data-theme") == theme,
                "The actual report did not apply its selected appearance")
            page.locator("#appearance > summary").click()
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 960})
                self.capture(f"report-{theme}-{width}")

    def run(self):
        self.prepare()
        self.tagged_drill_and_return()
        self.web_report_return()
        state = self.facts()
        assert len(state["expenses"]) == 3 and all(row["status"] == "confirmed" for row in state["expenses"])
        assert state["tagged_stats"]["total_amount_cents"] == 1900
        assert state["all_stats"]["total_amount_cents"] == 2700
        assert state["revision_reasons"].count("DrillAmount") == state["revision_reasons"].count("ReportReturn") == 1
        state["verified_leg"] = ("Actual tagged and unfiltered native category drills, original fact correction, "
            "return with retained scope and refreshed summary, Web report drill/correction/return with original "
            "month/currency/granularity/ranking/category, wide/narrow appearances and unchanged unrelated facts")
        return state
