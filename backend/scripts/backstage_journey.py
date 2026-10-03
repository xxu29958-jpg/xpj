"""Actual OCR configuration, upload, durable task, source and native review."""

from __future__ import annotations

import json

from scripts.backstage_journey_facts import denied_membership, facts, synthetic_receipt
from scripts.planning_journey_android import wait_for


class BackstageJourney:
    def __init__(self, page, native, fixture, evidence, base_url, advisor, restart_backend):
        self.page, self.native, self.fixture = page, native, fixture
        self.evidence, self.base_url = evidence, base_url
        self.ledger_id = fixture.ledger_id
        self.port = int(base_url.rsplit(":", 1)[1])
        self.advisor = advisor
        self.restart_backend = restart_backend

    def facts(self):
        return facts(self.ledger_id)

    def goto(self, path, *, page=None):
        return (page or self.page).goto(f"{self.base_url}{path}?ledger_id={self.ledger_id}")

    def capture(self, name, *, page=None):
        page = page or self.page
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "The actual Web page overflows"
        page.screenshot(path=self.evidence / f"web-backstage-{name}.png", full_page=True)

    def configure_ocr(self, *, provider="rapidocr", automatic=True):
        # Only the existing Owner form changes the isolated runtime configuration.
        owner = self.page.context.browser.new_page()
        try:
            owner.goto(self.base_url + "/owner/settings/recognition")
            form = owner.locator('form[action="/owner/settings/recognition"]')
            form.locator('[name="ocr_provider"]').select_option(provider)
            form.locator('[name="ocr_auto_run"]').set_checked(automatic)
            form.locator('[name="ocr_fallback_provider"]').select_option("empty")
            if provider == "local_llm":
                form.locator('[name="local_llm_base_url"]').fill("http://127.0.0.1:9/v1")
                form.locator('[name="local_llm_model"]').fill("intentionally-unreachable")
            form.get_by_role("button", name="保存识别设置", exact=True).click()
            assert form.locator('[name="ocr_provider"]').input_value() == provider
            self.capture(f"owner-{provider}-{'auto' if automatic else 'manual'}", page=owner)
        finally:
            owner.close()

    def upload_web(self):
        self.page.goto(self.base_url + "/web/auth/local?next=/web/pending")
        self.page.locator(f'input[name="ledger_id"][value="{self.ledger_id}"]').check()
        self.page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
        self.page.wait_for_url("**/web/pending*")
        self.native.bind(self.fixture.pairing_code, self.port)
        self.native.domain_home("收件")
        wait_for(lambda: self.native.has("还没有待处理的小票"), "The native empty inbox did not settle")
        self.native.capture("inbox-empty")
        self.capture("inbox-empty")
        self.configure_ocr()
        original = self.evidence / "synthetic-receipt-web.png"
        digest = synthetic_receipt(original)
        form = self.page.locator("#capture")
        before_selection = self.facts()
        with self.page.expect_file_chooser() as picker:
            form.get_by_label("选择小票图片", exact=True).click()
        picker.value.set_files(original)
        self.capture("inbox-selected-original")
        assert self.facts() == before_selection, "Selecting a file must not upload or create financial facts"
        form.get_by_role("button", name="上传小票", exact=True).click()
        wait_for(lambda: len(self.facts()["tasks"]) == 1, "The Web upload did not create its durable task")
        wait_for(lambda: self.facts()["tasks"][0]["status"] in ("completed", "failed"),
                 "Real OCR did not finish", 180)
        result = self.facts()
        assert result["tasks"][0]["status"] == "completed", result["tasks"]
        expense = result["expenses"][0]
        assert expense["amount"] == 1851 and expense["status"] == "pending", result
        assert expense["expense_time"] is not None and expense["original_sha256"] == digest
        assert result["tasks"][0]["expense_id"] == expense["id"]
        self.expense_id = expense["id"]
        self.task_id = result["tasks"][0]["id"]
        self.original_task = result["tasks"][0]
        self.capture_pending_queue()
        self.goto("/web/pending")
        self.page.locator("#recognition > summary").click()
        task = self.page.locator(f'[data-recognition-task-id="{self.task_id}"]')
        assert "已完成" in task.inner_text() and "待确认账单" in task.inner_text()
        self.capture("upload-result")
        task.get_by_role("link", name=f"打开原单 #{self.expense_id}", exact=True).click()
        assert self.page.locator('[name="amount_yuan"]').input_value() == "18.51"
        self.capture("original-pending")

    def open_tasks(self):
        for _ in range(6):
            nodes = list(self.native.tree().iter("node"))
            texts = {node.attrib.get("text") for node in nodes}
            descriptions = {node.attrib.get("content-desc") for node in nodes}
            if "后台任务" in texts and "返回设置" in descriptions:
                self.native.click("刷新")
                break
            if "打开账户与设置" in descriptions:
                self.native.click("打开账户与设置", stable=True)
                self.native.click("后台任务", stable=True)
            elif "后台任务" in texts:
                self.native.click("后台任务", stable=True)
            else:
                self.native.back()
        else:
            raise AssertionError("The actual navigation did not reach background tasks")
        wait_for(lambda: self.native.has("小票识别"), "Native did not rediscover the durable OCR task")

    def owner_results_navigation(self):
        # Management navigation must enter the signed-in person's existing task query.
        before = self.facts()
        self.page.goto(self.base_url + "/owner/diagnostics")
        with self.page.expect_popup() as popup:
            self.page.get_by_role("link", name="查看我的近期上传识别", exact=True).click()
        result = popup.value
        try:
            result.wait_for_url("**/web/pending*")
            history = result.locator("#recognition")
            if history.get_attribute("open") is None:
                history.locator("summary").click()
            task = result.locator(f'[data-recognition-task-id="{self.task_id}"]')
            assert result.locator("[data-recognition-task-id]").count() == 1
            assert "已完成" in task.inner_text()
            self.capture("owner-to-personal-task", page=result)
            task.get_by_role("link", name=f"打开原单 #{self.expense_id}", exact=True).click()
            assert result.locator('[name="amount_yuan"]').input_value() == "18.51"
            self.capture("owner-to-original", page=result)
            assert self.facts() == before
        finally:
            result.close()

    def task_read_recovery(self):
        self.open_tasks()
        self.native.capture("backstage-task-from-web")
        self.native.connection(self.port, online=False)
        try:
            self.native.click("刷新")
            # This emulator uses adb reverse with loopback; the shared network mapper
            # reports its existing phone-address diagnostic after the reverse is removed.
            wait_for(lambda: self.native.has("请填写可在手机上访问的地址"),
                     "The isolated route failure was not presented", 90)
            assert self.native.has("小票识别") and self.native.has("打开原账单")
            self.native.capture("backstage-offline-retained")
        finally:
            self.native.connection(self.port, online=True)
        before = self.facts()
        with denied_membership(self.ledger_id):
            self.native.click("刷新")
            wait_for(lambda: not self.native.has("打开原账单"), "Revoked task read still exposes its original source")
            assert all(node.attrib.get("text") != "小票识别" for node in self.native.tree().iter("node"))
            assert not self.native.has("绑定账本")
            self.native.capture("backstage-read-refused")
        self.native.click("刷新")
        wait_for(lambda: self.native.has("打开原账单"), "Restored membership did not reread the original task")
        assert self.facts() == before, "A read/refusal/recovery changed the underlying task or expense"
        self.native.restart()
        self.open_tasks()
        self.native.capture("backstage-task-after-restart")

    def retry_web(self):
        self.configure_ocr(provider="local_llm")
        self.goto(f"/web/expenses/{self.expense_id}/edit")
        draft = self.page.locator(f'form[action="/web/expenses/{self.expense_id}/save"]')
        draft.locator('[name="amount_yuan"]').fill("19.00")
        draft.locator('[name="note"]').fill("原窗口尚未保存的核对")
        retry = self.page.locator(f'form[action="/web/expenses/{self.expense_id}/ocr/retry"]')
        original_key = retry.locator('[name="idempotency_key"]').input_value()
        original_version = retry.locator('[name="expected_row_version"]').input_value()
        with self.page.expect_popup() as popup:
            retry.get_by_role("button", name="重试识别", exact=True).click()
        result = popup.value
        try:
            result.get_by_role("heading", name="暂未取得本次识别结果").wait_for()
            original_retry = result.locator('form[action$="/ocr/retry"]')
            assert original_retry.locator('[name="idempotency_key"]').input_value() == original_key
            assert original_retry.locator('[name="expected_row_version"]').input_value() == original_version
            self.capture("ocr-failure-original-request", page=result)
            self.configure_ocr()
            self.restart_backend()
            original_retry.get_by_role("button", name="重试原识别请求", exact=True).click()
            result.wait_for_url("**/edit?*")
            assert result.locator('[name="amount_yuan"]').input_value() == "18.51"
            self.capture("ocr-original-request-recovered", page=result)
            assert draft.locator('[name="amount_yuan"]').input_value() == "19.00"
            assert draft.locator('[name="note"]').input_value() == "原窗口尚未保存的核对"
            assert self.facts()["tasks"][0] == self.original_task, "Manual OCR rewrote the original asynchronous task"
            self.capture("ocr-original-window-preserved")
        finally:
            result.close()

    def native_review(self):
        self.native.click("打开原账单")
        self.native.reveal_any("18.51")
        self.native.capture("backstage-native-original-review")
        self.native.fill("19.00", previous=r"18\.51")
        self.native.click("确认入账")
        wait_for(lambda: self.facts()["expenses"][0]["status"] == "confirmed", "Native human review did not confirm the original", 90)
        assert self.facts()["expenses"][0]["amount"] == 1900
        self.goto(f"/web/expenses/{self.expense_id}/edit")
        assert "19.00" in self.page.inner_text("main")
        self.capture("human-confirmed-native-amount")

    def capture_pending_queue(self):
        before = self.facts()
        for theme in ("paper", "midnight"):
            self.page.set_viewport_size({"width": 1280, "height": 960})
            self.goto("/web/pending")
            self.page.locator("#appearance > summary").click()
            self.page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            self.page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
            self.page.locator("#appearance > summary").click()
            for width in (1280, 390):
                self.page.set_viewport_size({"width": width, "height": 960})
                self.goto("/web/pending")
                self.capture(f"inbox-queue-{width}-{theme}")
                self.page.locator('.inbox-filters a[href*="filter=ready"]').click()
                assert self.page.locator(".exp-row").filter(has_text="18.51").count() == 1
                assert self.page.locator('.inbox-filters [aria-current="page"]').evaluate("""node => {
                    const selected = node.getBoundingClientRect();
                    const viewport = node.parentElement.getBoundingClientRect();
                    return selected.left >= viewport.left - 1 && selected.right <= viewport.right + 1;
                }"""), "The selected inbox filter is outside the visible filter strip"
                self.capture(f"inbox-ready-{width}-{theme}")
        assert self.facts() == before, "Reading the real inbox filters changed the original bill or task"

    def appearances(self):
        for theme in ("paper", "midnight"):
            self.page.set_viewport_size({"width": 1280, "height": 960})
            self.goto("/web/pending")
            self.page.locator("#appearance > summary").click()
            self.page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            self.page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
            self.page.locator("#appearance > summary").click()
            for width in (1280, 390):
                self.page.set_viewport_size({"width": width, "height": 960})
                self.goto("/web/pending")
                self.page.locator("#recognition > summary").click()
                self.capture(f"task-result-{width}-{theme}")
        self.native.adb("shell", "cmd", "uimode", "night", "yes")
        self.native.restart()
        self.open_tasks()
        self.native.capture("backstage-task-midnight")

    def run(self):
        from scripts.backstage_journey_advisor import advisor_consumers
        from scripts.backstage_journey_fx import fx_consumers
        from scripts.backstage_journey_native import native_inbox_filters, native_upload_and_ocr
        from scripts.backstage_journey_ocr_recovery import drawer_lost_ocr_reply

        self.upload_web()
        native_inbox_filters(self)
        self.owner_results_navigation()
        self.task_read_recovery()
        self.retry_web()
        drawer_lost_ocr_reply(self)
        self.native_review()
        self.appearances()
        native_upload_and_ocr(self)
        advisor = advisor_consumers(self)
        try:
            fx_consumers(self)
        finally:
            (self.evidence / "fx-consumer-observation.json").write_text(json.dumps({
                "facts": self.facts(), "provider_requests": self.advisor.fx_requests,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        result = self.facts()
        result["advisor"] = advisor
        result["verified_leg"] = "Real RapidOCR and dated FX; Owner configuration and personal-result navigation; Web/Android image intake; task/source read refusal, recovery and restart; same-key OCR recovery after restart and lost reply; native OCR with auto mode disabled; explicit review preserving raw input/OCC; human confirmation; advisor consent, roles and audit with labelled synthetic upstream"
        return result
