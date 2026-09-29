"""Use Android's real image-share intake and durable OCR command consumer."""

import re

from scripts.backstage_journey_facts import synthetic_receipt
from scripts.planning_journey_android import wait_for


def share_synthetic_receipt(j):
    path = j.evidence / "synthetic-receipt-native.png"
    synthetic_receipt(path, amount="23.45")
    device_path = "/sdcard/Pictures/backstage-native.png"
    j.native.adb("push", str(path), device_path)
    j.native.adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                 "-d", "file://" + device_path)

    def media_id():
        rows = j.native.adb("shell", "content", "query", "--uri", "content://media/external/images/media",
                            "--projection", "_id:_display_name")
        matches = [re.search(r"_id=(\d+)", row) for row in rows.splitlines()
                   if "_display_name=backstage-native.png" in row]
        assert len(matches) <= 1, "The isolated shared image is ambiguous"
        return matches[0].group(1) if matches and matches[0] else None

    image_id = wait_for(media_id, "The emulator did not admit the synthetic shared image")
    j.native.adb("shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "image/png",
                 "--eu", "android.intent.extra.STREAM", f"content://media/external/images/media/{image_id}",
                 "--grant-read-uri-permission", "-n", "com.ticketbox/.MainActivity")


def open_latest_source(j):
    j.open_tasks()
    nodes = [node for node in j.native.tree().iter("node")
             if node.attrib.get("text") == "打开原账单" and node.attrib.get("enabled") != "false"]
    assert nodes, "The real task list has no original source action"
    # Existing task query orders newest first; choose its visible source action.
    j.native.tap(min(nodes, key=lambda node: j.native.bounds(node)[1]))
    wait_for(lambda: j.native.has("确认账单"), "The uploaded task did not open its original pending bill")


def native_upload_and_ocr(j):
    j.configure_ocr(automatic=False)
    count = len(j.facts()["expenses"])
    share_synthetic_receipt(j)
    wait_for(lambda: len(j.facts()["expenses"]) == count + 1, "Android did not upload its actual shared original", 90)
    wait_for(lambda: j.facts()["tasks"][-1]["status"] == "completed", "The automatic-disabled task did not settle")
    original = j.facts()["expenses"][-1]
    original_task = j.facts()["tasks"][-1]
    assert original["amount"] is None and original["status"] == "pending"
    assert original_task["expense_id"] == original["id"] and original_task["result"]["outcome"] == "no_result"
    open_latest_source(j)
    j.native.fill("27.00", label="金额")
    j.native.reveal_any("重新识别")
    j.native.click("重新识别")
    wait_for(lambda: j.facts()["expenses"][-1]["amount"] == 2345, "Explicit Android OCR did not run with automatic OCR disabled", 180)
    wait_for(lambda: j.native.has("原操作已完成"), "The original native OCR command has no accepted outcome", 90)
    j.native.reveal_any("27.00", toward_start=True)
    j.native.capture("backstage-native-ocr-preserved-input")
    assert j.facts()["expenses"][-1]["status"] == "pending", "OCR confirmed a bill without human review"
    j.native.reveal_any("加载最新账单")
    j.native.click("加载最新账单")
    j.native.click("保留填写")
    j.native.reveal_any("27.00", toward_start=True)
    j.native.reveal_any("加载最新账单")
    j.native.click("加载最新账单")
    j.native.click("替换并载入")
    j.native.reveal_any("23.45", toward_start=True)
    j.native.capture("backstage-native-ocr-explicit-review")
    current = j.facts()
    assert current["tasks"][-1] == original_task, "Manual native OCR rewrote the original upload result"
    assert current["expenses"][-1]["original_sha256"] == original["original_sha256"]
    j.goto("/web/pending")
    j.page.locator("#recognition > summary").click()
    task = j.page.locator(f'[data-recognition-task-id="{original_task["id"]}"]')
    assert "当次未识别出可用字段" in task.inner_text()
    task.get_by_role("link", name=f'打开原单 #{original["id"]}', exact=True).click()
    assert j.page.locator('[name="amount_yuan"]').input_value() == "23.45"
    j.capture("native-ocr-current-source-original-task-retained")
