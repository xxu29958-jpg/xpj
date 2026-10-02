"""Use Android's real image-share intake and durable OCR command consumer."""

import re

from scripts.backstage_journey_facts import synthetic_receipt
from scripts.planning_journey_android import wait_for


def native_inbox_filters(j):
    before = j.facts()
    j.native.restart()
    j.native.domain_home("收件")
    wait_for(lambda: j.native.has("全部 1"), "The inbox did not reread the Web-uploaded pending bill")
    j.native.capture("inbox-pending")
    j.native.click_counted_tab("疑似重复")
    empty = "没有符合「疑似重复」的待确认账单"
    wait_for(lambda: j.native.has(empty), "The zero-match filter did not explain its empty result")
    j.native.capture("inbox-filter-empty")
    j.native.click_counted_tab("全部")
    wait_for(lambda: not j.native.has(empty) and j.native.has("18.51"),
             "The user could not return from the empty filter to the original pending bill")
    for action, destination in (("还款复核", "还款采集"), ("数据质量", "检查当前账本的待确认、分类完整性与凭证状态。")):
        j.native.click("收件工具")
        j.native.capture("inbox-tools")
        j.native.click(action)
        wait_for(lambda destination=destination: j.native.has(destination),
                 "The inbox tool did not open its existing consumer")
        j.native.domain_home("收件")
        wait_for(lambda: j.native.has("18.51"), "Returning from an inbox tool lost the pending bill")
    previous_scale = j.native.adb("shell", "settings", "get", "system", "font_scale").strip()
    try:
        j.native.adb("shell", "settings", "put", "system", "font_scale", "1.8")
        j.native.restart()
        j.native.domain_home("收件")
        wait_for(lambda: j.native.has("上传小票") and j.native.has("收件工具"),
                 "Large text hid an inbox header action")
        j.native.capture("inbox-large-text")
        j.native.click("收件工具")
        j.native.click("完成")
    finally:
        if previous_scale == "null":
            j.native.adb("shell", "settings", "delete", "system", "font_scale")
        else:
            j.native.adb("shell", "settings", "put", "system", "font_scale", previous_scale)
        j.native.restart()
        j.native.domain_home("收件")
    assert j.facts() == before, "Browsing inbox filters and tools changed the original bill or upload task"


def share_synthetic_receipt(j):
    path = j.evidence / "synthetic-receipt-native.png"
    digest = synthetic_receipt(path, amount="23.45", date_text="2025年1月12日")
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
    uri = f"content://media/external/images/media/{image_id}"
    # Shell-started intents do not perform an app sender's EXTRA_STREAM -> ClipData
    # handoff. Put the same URI in data so its explicit read grant has a target.
    j.native.adb("shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "image/png",
                 "-d", uri, "--eu", "android.intent.extra.STREAM", uri,
                 "--grant-read-uri-permission", "-n", "com.ticketbox/.MainActivity")
    return digest


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
    digest = share_synthetic_receipt(j)
    wait_for(lambda: len(j.facts()["expenses"]) == count + 1, "Android did not upload its actual shared original", 90)
    wait_for(lambda: j.facts()["tasks"][-1]["status"] == "completed", "The automatic-disabled task did not settle")
    original = j.facts()["expenses"][-1]
    original_task = j.facts()["tasks"][-1]
    assert original["amount"] is None and original["status"] == "pending"
    assert original["original_sha256"] == digest, "The actual share did not preserve its synthetic original"
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
