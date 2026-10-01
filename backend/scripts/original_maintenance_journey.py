"""Real Owner forms, immutable manifests, file failures and process interruption."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app.database import SessionLocal
from app.models import BackgroundTask, Expense
from app.services.file_service import resolve_upload_path_for_tenant
from scripts.backstage_journey_facts import synthetic_receipt
from scripts.planning_journey_android import wait_for
from scripts.portable_journey_facts import attach_fixture_original


class OriginalMaintenanceJourney:
    def __init__(self, page, native, fixture, evidence, base_url, restart_backend):
        self.page, self.native, self.fixture = page, native, fixture
        self.evidence, self.base_url, self.restart_backend = evidence, base_url, restart_backend
        self.ledger = fixture.ledger_id
        self.uploads = Path(os.environ["UPLOAD_DIR"])
        sample = evidence / "orphan-fixture-receipt.png"
        synthetic_receipt(sample, amount="12.34", date_text="2026年10月1日")
        self.sample = sample.read_bytes()

    def goto(self, task_id=None):
        response = self.page.goto(f"{self.base_url}/owner/originals?ledger_id={self.ledger}"
            + (f"&task_id={task_id}" if task_id else ""))
        assert response.ok, f"Owner original storage returned {response.status}"

    def state(self, public_id):
        with SessionLocal() as db:
            task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id))
            return {"id": task.public_id, "status": task.status, "error_code": task.error_code,
                "result": json.loads(task.result_summary_json or "{}"), "input": json.loads(task.input_payload_json)}

    def complete(self, public_id):
        state = wait_for(lambda: (value := self.state(public_id))["status"] in {"completed", "failed", "cancelled"} and value,
            "The durable original task did not finish", 90)
        assert state["status"] == "completed", state["error_code"]
        self.goto(public_id)
        return state

    def submit(self, action):
        form = self.page.locator(f'form[action="{action}"]')
        if action.endswith("/dispose"):
            form.locator('[name="confirmed"]').check()
        form.locator('button[type="submit"]').click()
        self.page.wait_for_url("**/owner/originals?*task_id=*")
        return parse_qs(urlsplit(self.page.url).query)["task_id"][0]

    def inspect(self):
        self.goto()
        public_id = self.submit("/owner/originals/inspect")
        return self.complete(public_id)

    def submit_with_reply_loss(self, action):
        accepted = []

        def lose_reply(route):
            response = route.fetch(max_redirects=0)
            assert response.status == 303, "The original disposal was not accepted before reply loss"
            accepted.append(parse_qs(urlsplit(response.headers["location"]).query)["task_id"][0])
            route.abort("connectionclosed")

        self.page.route("**" + action, lose_reply)
        form = self.page.locator(f'form[action="{action}"]')
        form.locator('[name="confirmed"]').check()
        try:
            with self.page.expect_request_failed(lambda request: request.method == "POST" and request.url.endswith(action)):
                form.locator('button[type="submit"]').click(no_wait_after=True)
        finally:
            self.page.unroute("**" + action, lose_reply)
        assert len(accepted) == 1
        self.goto()
        self.page.locator(".original-task-history a").first.click()
        recovered = parse_qs(urlsplit(self.page.url).query)["task_id"][0]
        assert recovered == accepted[0], "Reopening history did not recover the original accepted task"
        return recovered

    def capture(self, name):
        assert not self.page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Owner page overflows"
        self.page.screenshot(path=self.evidence / f"owner-originals-{name}.png", full_page=True)

    def old_file(self, name, *, ledger=None):
        path = self.uploads / (ledger or self.ledger) / "2026" / "01" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.sample)
        os.utime(path, (1_700_000_000, 1_700_000_000))
        return path

    def expense(self):
        with SessionLocal() as db:
            row = db.scalar(select(Expense).where(Expense.tenant_id == self.ledger))
            return {"id": row.id, "amount": row.amount_cents, "revision": row.fact_revision,
                "row_version": row.row_version, "image_path": row.image_path, "image_hash": row.image_hash}

    def create_retained_fact(self):
        page = self.page
        page.goto(self.base_url + "/web/auth/local?next=/web/expenses/new")
        page.locator(f'input[name="ledger_id"][value="{self.ledger}"]').check()
        page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
        page.wait_for_url("**/web/expenses/new*")
        form = page.locator('form[action="/web/expenses/new"]')
        form.locator('[name="amount_major"]').fill("12.34")
        form.get_by_role("button", name="记下这笔支出", exact=True).click()
        page.wait_for_url("**/web/expenses/*/edit*")
        self.digest = attach_fixture_original(self.expense()["id"], ledger_id=self.ledger)
        self.baseline = self.expense()
        path = resolve_upload_path_for_tenant(self.baseline["image_path"], self.ledger)
        os.utime(path, (1_700_000_000, 1_700_000_000))

    def appearances(self, task_id):
        for theme in ("paper", "midnight"):
            self.page.context.add_cookies([{"name": "ui_theme", "value": theme, "url": self.base_url}])
            for width in (1280, 390):
                self.page.set_viewport_size({"width": width, "height": 960})
                self.goto(task_id)
                assert self.page.locator("html").get_attribute("data-theme") == theme
                images = self.page.locator(".original-candidate img")
                assert images.count() == 12
                images.first.scroll_into_view_if_needed()
                wait_for(lambda images=images: images.first.evaluate("image => image.complete && image.naturalWidth > 0"), "Candidate preview did not load")
                button = self.page.get_by_role("button", name="删除本次候选文件", exact=True)
                assert button.bounding_box()["height"] >= 44
                button.focus()
                assert button.evaluate("button => button === document.activeElement")
                self.capture(f"candidates-{width}-{theme}")
        self.page.get_by_role("link", name="下一页文件", exact=True).click()
        assert self.page.locator(".original-candidate").count() == 2
        self.capture("candidate-page-two")
        self.goto(task_id)

    def partial_disposal(self):
        files = [self.old_file("locked/0.png")] + [self.old_file(f"first-{index}.png") for index in range(1, 14)]
        self.other = self.old_file("other-ledger.png", ledger="orphan-other-isolation")
        inspection = self.inspect()
        assert inspection["result"]["candidate_files"] == 14
        assert inspection["result"]["protected_files"] == 1
        self.appearances(inspection["id"])
        assert all(path.exists() for path in files), "Inspection deleted bytes"
        self.old_file("late-first.png")
        files[1].write_bytes(self.sample + b"changed since inspection")
        os.utime(files[1], (1_700_000_000, 1_700_000_000))
        files[0].parent.chmod(0o555)
        try:
            public_id = self.submit_with_reply_loss(f"/owner/originals/tasks/{inspection['id']}/dispose")
            partial = self.complete(public_id)
        finally:
            files[0].parent.chmod(0o755)
        result = partial["result"]
        assert (result["deleted_files"], result["failed_files"], result["changed_files"]) == (12, 1, 1)
        assert "仍有文件待处理" in self.page.inner_text("#original-task")
        self.capture("partial-disposal")
        child = self.complete(self.submit(f"/owner/originals/tasks/{public_id}/continue"))
        assert (child["result"]["candidate_files"], child["result"]["deleted_files"]) == (1, 1)
        assert self.state(public_id) == partial, "Continuation rewrote the original partial result"
        assert files[1].exists() and self.other.exists()
        return {key: result[key] for key in ("candidate_files", "deleted_files", "failed_files", "changed_files")}

    def interrupted_disposal(self):
        for index in range(33):
            self.old_file(f"interrupt-{index}.png")
        inspection = self.inspect()
        assert inspection["result"]["candidate_files"] == 35
        gate = Path(os.environ["TICKETBOX_DATA_DIR"]) / "orphan-pause-after-checkpoint"
        gate.write_text("pause this isolated task after its durable first chunk", encoding="utf-8")
        public_id = self.submit(f"/owner/originals/tasks/{inspection['id']}/dispose")
        wait_for(gate.with_suffix(".reached").exists, "The first real disposal chunk was not persisted")
        before = self.state(public_id)
        assert before["status"] == "running" and before["result"]["deleted_files"] == 32
        self.goto(public_id)
        self.capture("before-process-interruption")
        self.restart_backend(abrupt=True)
        gate.unlink()
        self.goto(public_id)
        interrupted = self.state(public_id)
        assert interrupted["status"] == "failed" and interrupted["error_code"] == "orphaned_after_restart"
        assert interrupted["result"] == before["result"] and interrupted["input"] == before["input"]
        self.capture("after-process-restart")
        late = self.old_file("after-process-interruption.png")
        child = self.complete(self.submit(f"/owner/originals/tasks/{public_id}/continue"))
        assert child["result"]["candidate_files"] == child["result"]["deleted_files"] == 3
        assert late.is_file() and self.other.is_file()
        self.capture("continued-original-remainder")
        return {"before_interruption_deleted": 32, "continued_candidates": 3, "later_file_retained": late.exists()}

    def native_observations(self):
        self.native.bind(self.fixture.pairing_code, urlsplit(self.base_url).port)
        self.native.click("打开账户与设置", stable=True)
        self.native.click("后台任务", stable=True)
        wait_for(lambda: self.native.has("处置已核对文件"), "Native did not read the real disposal task")
        self.native.reveal_any("检查未引用文件")
        self.native.reveal_any("原件存储")
        self.native.capture("original-maintenance-tasks")

    def run(self):
        self.create_retained_fact()
        # Real repeated inspections also exercise reopening/pagination of durable history.
        for _ in range(12):
            assert self.inspect()["result"]["candidate_files"] == 0
        self.capture("no-candidates")
        partial = self.partial_disposal()
        self.page.get_by_role("link", name="更早的任务", exact=True).click()
        assert "第 2 页" in self.page.inner_text('section[aria-label="原件任务历史"]')
        self.capture("history-page-two")
        interrupted = self.interrupted_disposal()
        self.native_observations()
        assert self.expense() == self.baseline, "Maintenance rewrote a retained financial fact"
        original = resolve_upload_path_for_tenant(self.baseline["image_path"], self.ledger)
        assert hashlib.sha256(original.read_bytes()).hexdigest() == self.digest
        return {"partial_disposal": partial, "restart": interrupted, "retained_original_sha256": self.digest,
            "retained_amount_cents": self.baseline["amount"], "history_paginated": True,
            "verified_leg": "Actual Owner inspection/preview/confirmation, accepted reply loss and history recovery, filesystem partial failure, frozen continuation, process kill/restart, paginated task history, both widths/themes and native task observations"}
