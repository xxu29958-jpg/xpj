"""Organize one real ledger through Web and native Reference consumers."""

from urllib.parse import urlsplit

from scripts.planning_journey_android import wait_for
from scripts.reference_journey_facts import facts


class ReferenceJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.page, self.native, self.fixture, self.evidence = page, native, fixture, evidence
        self.base_url, self.port = base_url, urlsplit(base_url).port

    def facts(self):
        return facts(self.fixture.ledger_id)

    def expect(self, predicate, reason):
        return wait_for(lambda: predicate(self.facts()), reason, 90)

    def goto(self, path):
        return self.page.goto(f"{self.base_url}{path}{'&' if '?' in path else '?'}ledger_id={self.fixture.ledger_id}")

    def form(self, action):
        return self.page.locator(f'form[action="{action}"]')

    def confirm(self, form):
        form.locator('button[type="submit"]').click()
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            self.page.locator('#tb-confirm-modal[open]').get_by_role("button", name="确认", exact=True).click()

    def capture(self, name):
        assert not self.page.evaluate("document.documentElement.scrollWidth > innerWidth"), "The reference page overflows"
        self.page.screenshot(path=self.evidence / f"web-reference-{name}.png", full_page=True)

    def native_open(self, label):
        self.native.domain_home("流水")
        self.native.click("筛选与工具")
        self.native.click("资料库")
        self.native.click(label)

    def native_row_action(self, label, action):
        # Compose exposes these list labels as siblings in one panel, not row
        # ancestors. Match the live touch bounds of the button beside the label.
        def locate():
            root = self.native.tree()
            parents = {child: parent for parent in root.iter() for child in parent}
            labels = [node for node in root.iter("node") if node.get("text") == label]
            matches = []
            for node in root.iter("node"):
                if action not in (node.get("content-desc"), node.get("text")):
                    continue
                button = node if node.get("clickable") == "true" else parents.get(node, node)
                if button.get("enabled") == "false":
                    continue
                left, top, _, bottom = self.native.bounds(button)
                for text in labels:
                    _, y1, right, y2 = self.native.bounds(text)
                    if right <= left and top <= (y1 + y2) // 2 <= bottom:
                        matches.append(button)
            return matches if len(matches) == 1 else None
        button = wait_for(locate, f"The visible {action} beside {label} cannot be identified")[0]
        self.native.tap(button)

    def tag(self, name):
        return next(row for row in self.facts()["tags"] if row["name"] == name)

    def tag_editor(self, public_id, action):
        self.goto("/web/tags")
        row = self.page.locator(f'#tag-{public_id}')
        row.locator("summary").click()
        row.locator(f'a[href*="action={action}"]').click()
        return self.form(f"/web/tags/{public_id}/{action}")

    def rule(self, identity):
        return next(row for row in self.facts()["rules"] if row["id"] == identity)

    def batch(self, expense_ids, field, value):
        self.goto("/web/confirmed")
        self.page.get_by_role("button", name="选择", exact=True).click()
        for identity in expense_ids:
            self.page.locator(f'.row-check[data-id="{identity}"]').check()
        form = self.page.locator("#bulk-form")
        form.get_by_text("批量更正", exact=True).click()
        form.locator('[name="reason"]').fill("资料库联动核对")
        form.locator(f'[name="{field}"]').fill(value)
        form.locator(f'button[name="action"][value="set_{field}"]').click()
        self.expect(lambda state: all(row[field] == value for row in state["expenses"] if row["id"] in expense_ids),
                    "The actual confirmed batch command did not preserve the selected facts")

    def initial_facts(self):
        page = self.page
        page.goto(self.base_url + "/web/auth/local?next=/web/expenses/new")
        page.locator(f'input[name="ledger_id"][value="{self.fixture.ledger_id}"]').check()
        self.form("/web/auth/local").locator('button[type="submit"]').click()
        page.wait_for_url("**/web/expenses/new*")
        for index, (amount, category) in enumerate((("12.34", "其他"), ("25.00", "其他"), ("7.50", "Library")), 1):
            self.goto("/web/expenses/new")
            form = self.form("/web/expenses/new")
            form.locator('[name="amount_major"]').fill(amount)
            if not form.locator('[name="merchant"]').is_visible():
                form.locator("details.manual-expense-options > summary").click()
            form.locator('[name="merchant"]').fill("RefPay")
            form.locator('[name="category"]').fill(category)
            form.get_by_role("button", name="记下这笔支出", exact=True).click()
            self.expect(lambda state, index=index: len(state["expenses"]) == index, "The actual manual entry did not commit")
        records = self.facts()["expenses"]
        self.batch([row["id"] for row in records[:2]], "tags", "Trip")
        self.batch([records[2]["id"]], "tags", "Monthly")
        self.goto("/web/confirmed?tag=Trip")
        page.get_by_text("保存当前视图", exact=True).click()
        form = self.form("/web/saved-views")
        form.locator('[name="name"]').fill("TripView")
        form.get_by_role("button", name="保存视图", exact=True).click()
        self.expect(lambda state: len(state["views"]) == 1, "The actual saved view was not retained")
        assert self.facts()["views"][0]["tag_id"] == self.tag("Trip")["id"]
        self.native.bind(self.fixture.pairing_code, self.port)

    def tag_edits(self):
        native, page = self.native, self.page
        original = self.tag("Trip")
        stale = self.tag_editor(original["id"], "rename")
        original_version = stale.locator('[name="expected_row_version"]').input_value()
        stale.locator('[name="name"]').fill("WebDraft")
        self.native_open("标签")
        native.reveal_any("Trip")
        self.native_row_action("Trip", "标签操作")
        native.click("重命名")
        native.fill("TripNew", previous="Trip")
        native.connection(self.port, online=False)
        try:
            native.click("保存")
            wait_for(lambda: native.has("重命名标签") and any(native.has(message) for message in
                     ("网络", "请填写可在手机上访问的地址", "服务暂时没有响应", "暂时连不上")),
                     "A rejected native tag rename lost its editor or did not report the failure")
            assert any(node.attrib.get("class") == "android.widget.EditText" and node.attrib.get("text") == "TripNew"
                       for node in native.tree().iter("node")), "The rejected rename lost the original input"
            assert self.tag("Trip") == original
            native.capture("reference-tag-rejected-original")
        finally:
            native.connection(self.port, online=True)
        native.click("保存")
        self.expect(lambda state: any(row["id"] == original["id"] and row["name"] == "TripNew" for row in state["tags"]),
                    "The original native rename could not continue")
        stale.locator('[data-tag-submit]').click()
        wait_for(lambda: stale.get_attribute("data-tag-draft-phase") == "blocked", "The stale original was not refused")
        assert self.form(f'/web/tags/{original["id"]}/rename').locator('[name="name"]').input_value() == "WebDraft"
        page.reload()
        wait_for(lambda: stale.get_attribute("data-tag-draft-phase") == "blocked", "Reload did not resume the rejected rename")
        assert stale.locator('[name="name"]').input_value() == "WebDraft"
        assert stale.locator('[name="expected_row_version"]').input_value() == original_version
        assert self.tag("TripNew")["id"] == original["id"], "A stale Web editor overwrote the native result"
        self.capture("tag-stale-web-input")
        view = self.facts()["views"][0]
        self.goto(f'/web/saved-views/{view["id"]}/open')
        assert page.locator('.row-check').count() == 2 and "TripNew" in page.inner_text("main")

        merge_action = f'/web/tags/{original["id"]}/merge'
        merge = self.tag_editor(original["id"], "merge")
        target = self.tag("Monthly")
        original_target = f'{target["id"]}:{target["row_version"]}'
        original_version = merge.locator('[name="expected_row_version"]').input_value()
        merge.locator('[name="target"]').select_option(original_target)
        self.native_row_action("Monthly", "标签操作")
        native.click("重命名")
        native.fill("MonthlyNew", previous="Monthly")
        native.click("保存")
        self.expect(lambda state: any(row["id"] == target["id"] and row["name"] == "MonthlyNew" for row in state["tags"]),
                    "The native target rename did not establish the real Web merge conflict")
        merge.locator('[data-tag-submit]').click()
        wait_for(lambda: merge.get_attribute("data-tag-draft-phase") == "blocked", "The stale merge was not refused")
        page.reload()
        wait_for(lambda: merge.get_attribute("data-tag-draft-phase") == "blocked", "Reload did not resume the rejected merge")
        self.capture("tag-merge-conflict-original-choice")
        retained = self.form(merge_action)
        assert retained.locator('[name="target"]').input_value() == original_target, "The rejected Web merge lost its chosen target"
        assert retained.locator('[name="expected_row_version"]').input_value() == original_version
        assert not self.tag("TripNew")["deleted"], "The stale merge committed instead of refusing"
        refreshed_target = self.tag("MonthlyNew")
        before_review = self.facts()
        with page.expect_navigation(wait_until="domcontentloaded"):
            retained.locator('[data-tag-review]').click()
        wait_for(lambda: retained.get_attribute("data-tag-draft-phase") == "editing", "Explicit review did not prepare the original merge")
        assert self.facts() == before_review, "Review must not mutate reference or expense facts"
        assert retained.locator('[name="target"]').input_value() == f'{target["id"]}:{refreshed_target["row_version"]}'
        retained.locator('[data-tag-submit]').click()
        self.expect(lambda state: any(row["id"] == original["id"] and row["deleted"] for row in state["tags"]),
                    "The explicitly reviewed Web merge did not commit")
        self.goto("/web/saved-views")
        assert "原标签已被删除或合并" in page.inner_text("main")
        assert page.locator(f'a[href*="/web/saved-views/{view["id"]}/open"]').count() == 0
        self.capture("missing-tag-view-requires-repair")
        records = self.facts()["expenses"]
        self.batch([records[0]["id"]], "tags", "Later")
        self.goto("/web/recycle-bin")
        mutation = self.facts()["tag_mutations"][0]
        restore = page.locator(f'[data-restore-key="tag_mutation:{mutation["id"]}"] form')
        self.confirm(restore)
        self.expect(lambda state: not state["tag_mutations"], "The shared recycle bin did not consume the undo snapshot")
        assert not self.tag("TripNew")["deleted"], "The source tag was not restored"
        assert "恢复 1 笔，跳过 1 笔已变更账单" in page.inner_text("main")
        records = self.facts()["expenses"]
        assert [row["tags"] for row in records] == ["Later", "TripNew", "MonthlyNew"], "Tag recovery overwrote a later edit"
        self.capture("tag-partial-recovery")
        self.goto(f'/web/saved-views/{view["id"]}/open')
        assert page.locator('.row-check').count() == 1
        assert page.locator('.row-check').get_attribute("data-id") == str(records[1]["id"])
        native.restart()
        self.native_open("标签")
        native.reveal_any("TripNew")
        native.capture("reference-tag-restored-from-web")

    def run(self):
        from scripts.reference_journey_merchants import organize_merchants
        from scripts.reference_journey_rules import organize_rules
        from scripts.reference_journey_views import qualify_consumers

        self.initial_facts()
        self.tag_edits()
        organize_merchants(self)
        organize_rules(self)
        qualify_consumers(self)
        result = self.facts()
        assert [row["amount"] for row in result["expenses"]] == [1234, 2500, 750]
        assert all(row["merchant"] == "RefPay" and row["status"] == "confirmed" for row in result["expenses"])
        assert [row["tags"] for row in result["expenses"]] == ["Later", "TripFinal", "MonthlyNew"]
        assert [row["category"] for row in result["expenses"]] == ["Manual", "其他", "Library"]
        result["verified_leg"] = "Actual tag/merchant editing and recovery, stable saved views, explicit rule preview/application/partial rollback, roles and both clients"
        return result
