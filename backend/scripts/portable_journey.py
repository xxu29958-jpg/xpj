"""Actual Web, Desktop bridge and Android system-save portable downloads."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from scripts.planning_journey_android import wait_for
from scripts.portable_journey_desktop import desktop_browser
from scripts.portable_journey_facts import (
    LEDGER,
    archive_fixture_ledger,
    attach_fixture_original,
    facts,
    pairing_code,
    seed_identity,
    verify_package,
)


class PortableJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.page, self.native, self.evidence, self.base_url = page, native, evidence, base_url
        self.public_url = base_url.replace("127.0.0.1", "localhost")
        self.port = urlsplit(base_url).port
        self.account = seed_identity()
        self.packages = {}
        self.original_digest = ""
        self.expected = {}

    def capture(self, page, name):
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Download entry overflows"
        page.screenshot(path=self.evidence / f"portable-{name}.png", full_page=True)

    def create_records(self):
        page = self.page
        page.goto(self.public_url + "/web/auth/login?next=/web/expenses/new")
        page.locator('[name="pairing_code"]').fill(pairing_code(self.account))
        page.locator('form[action="/web/auth/login"] button[type="submit"]').click()
        page.wait_for_url("**/web/expenses/new*")
        form = page.locator('form[action="/web/expenses/new"]')
        form.locator('[name="amount_major"]').fill("100.00")
        if not form.locator('[name="merchant"]').is_visible():
            form.locator("details.manual-expense-options > summary").click()
        form.locator('[name="merchant"]').fill("下载核对原流水")
        form.get_by_role("button", name="记下这笔支出", exact=True).click()
        wait_for(lambda: facts().get("amount_cents") == 10000, "The original expense was not created")
        page.goto(f"{self.public_url}/web/expenses/{facts()['id']}/edit?ledger_id={LEDGER}")
        page.get_by_role("link", name="更正这笔账单", exact=True).click()
        form = page.locator("form.correction-form")
        form.locator('[name="reason"]').fill("核对原记录与历史一起带走")
        form.locator('[name="amount_yuan"]').fill("120.00")
        form.locator('[name="note"]').fill("portable-history")
        form.get_by_role("button", name="保存更正", exact=True).click()
        wait_for(lambda: facts().get("amount_cents") == 12000, "The correction did not commit")
        self.expected = facts()
        self.original_digest = attach_fixture_original(self.expected["id"])

    def web_download(self, page, name, *, archived):
        assert page.locator(f'input[name="ledger_id"][value="{LEDGER}"]').is_checked()
        assert ("已归档" in page.locator(".auth-ledger-list").inner_text()) == archived
        self.capture(page, name)
        with page.expect_download(timeout=120000) as downloading:
            page.get_by_role("button", name="下载所选账本（ZIP）", exact=True).click()
        download = downloading.value
        target = self.evidence / f"{name}.zip"
        download.save_as(target)
        assert download.failure() is None
        self.packages[name] = verify_package(target, self.expected, self.original_digest, archived=archived)

    def native_entry(self):
        self.native.plan_home()
        self.native.click("打开账户与设置")
        self.native.click("数据与导出")
        self.native.reveal_any("便携下载核对账本")
        self.native.reveal_any("下载并保存完整数据包")

    def system_save(self, name):
        native = self.native
        native.click("下载并保存完整数据包")
        native.fill(name + ".zip", previous=r"ticketbox-portable\.zip")

        def save_button():
            matches = [node for node in native.tree().iter("node")
                if node.attrib.get("text", "").casefold() in {"save", "保存"}
                and node.attrib.get("enabled") == "true"]
            return matches if len(matches) == 1 else None

        button = wait_for(save_button, "The actual Android system save action is not unambiguous")
        native.capture("portable-system-picker-" + name)
        native.tap(button[0])

    def saved_paths(self, name):
        result = self.native.adb("shell", "find", "/sdcard/Download", "-maxdepth", "1", "-type", "f",
            "-name", name + ".zip")
        return [path.strip() for path in result.splitlines() if path.strip()]

    def native_download(self, name, *, archived):
        self.system_save(name)
        wait_for(lambda: self.native.has("完整数据包已保存。"), "The system destination never completed", 120)
        self.native.capture(name + "-saved")
        paths = self.saved_paths(name)
        assert len(paths) == 1, "The new system document was not saved in the selected Downloads location"
        target = self.evidence / f"{name}.zip"
        self.native.adb("pull", paths[0], str(target))
        self.packages[name] = verify_package(target, self.expected, self.original_digest, archived=archived)

    def appearances(self):
        for theme in ("paper", "midnight"):
            self.page.goto(self.public_url + f"/web/import?ledger_id={LEDGER}")
            self.page.locator("#appearance > summary").click()
            self.page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            self.page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
            self.page.locator("#appearance > summary").click()
            for width in (1280, 390):
                self.page.set_viewport_size({"width": width, "height": 960})
                self.page.goto(self.public_url + "/web/exports")
                assert self.page.locator("html").get_attribute("data-theme") == theme
                self.capture(self.page, f"selection-{width}-{theme}")
        self.native.plan_home()
        self.native.click("打开账户与设置")
        self.native.click("外观与主题")
        self.native.click("玄夜")
        self.native_entry()
        self.native.capture("portable-selection-midnight")

    def interrupted_destinations(self):
        gate = Path(os.environ["TICKETBOX_DATA_DIR"]) / "portable-transfer-delay"
        gate.write_text("isolated network delay", encoding="utf-8")
        try:
            self.system_save("native-cancelled")
            wait_for(lambda: self.native.has("已写入"), "The delayed download never started writing")
            self.native.click("取消")
            wait_for(lambda: self.native.has("已取消下载。"), "Cancelled download did not return to a usable state")
            wait_for(lambda: not self.saved_paths("native-cancelled"), "Cancel left the new incomplete document")
            self.native.capture("portable-cancelled")
            self.system_save("native-interrupted")
            wait_for(lambda: self.native.has("已写入"), "The interrupted download never began")
            self.native.restart()
            self.native_entry()
            self.native.capture("portable-after-process-stop")
            assert not self.native.has("完整数据包已保存。"), "A stopped transfer was reported as complete"
            wait_for(lambda: not self.saved_paths("native-interrupted"),
                "Restart silently left an incomplete ZIP in the system destination", 15)
        finally:
            gate.unlink(missing_ok=True)

    def run(self):
        self.create_records()
        self.native.bind(pairing_code(self.account), self.port)
        self.native_entry()
        self.native_download("native-active", archived=False)
        with desktop_browser(self.page.context.browser, self.base_url, LEDGER) as (desktop, origin):
            self.page.goto(self.public_url + "/web/exports")
            self.web_download(self.page, "web-active", archived=False)
            desktop.goto(origin + "/web/exports")
            self.web_download(desktop, "desktop-active", archived=False)
            self.appearances()
            archive_fixture_ledger(self.account)
            self.page.goto(self.public_url + "/web/pending")
            self.page.get_by_role("link", name="下载账本数据，包括拥有的已归档账本", exact=True).click()
            self.web_download(self.page, "web-no-active-ledger", archived=True)
            desktop.goto(origin + "/web/pending")
            desktop.get_by_role("link", name="下载有权访问的账本数据", exact=True).click()
            self.web_download(desktop, "desktop-no-active-ledger", archived=True)
            self.native.restart()
            self.native_entry()
            self.native.reveal_any("已归档")
            self.native_download("native-no-active-ledger", archived=True)
            self.interrupted_destinations()
        assert facts() == self.expected, "Taking data away changed the financial facts or their history"
        return {"ledger_id": LEDGER, "financial_facts": facts(), "packages": self.packages,
            "verified_leg": "Web, actual Desktop bridge and Android system save, active and archived owner with no active ledger, package reopen, history and original digests, cancellation and process interruption"}
