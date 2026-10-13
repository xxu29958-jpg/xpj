"""Continue a real native original selection across complete app-process death."""

import hashlib
from pathlib import PurePosixPath

from scripts.backstage_journey_facts import synthetic_receipt
from scripts.planning_journey_android import wait_for


def _pick_original(native):
    native.click("Show roots")
    native.click("Downloads")

    def locate():
        nodes = [node for node in native.tree().iter("node") if
            node.attrib.get("text") == "financial-selected-original.png" or
            node.attrib.get("content-desc", "").startswith("financial-selected-original.png,")]
        assert len(nodes) <= 1, "The system document picker contains an ambiguous fixture"
        return nodes
    nodes = wait_for(locate, "The system document picker did not expose the original fixture")
    native.capture("financial-original-system-picker")
    native.tap(nodes[0])


def _retained_key(native, digest):
    paths = native.adb("exec-out", "run-as", "com.ticketbox", "find", "files/upload-intents",
        "-name", "*.upload", "-type", "f").splitlines()
    matching = [PurePosixPath(path).stem for path in paths if hashlib.sha256(native.adb(
        "exec-out", "run-as", "com.ticketbox", "cat", path, binary=True)).hexdigest() == digest]
    assert len(matching) == 1, "The stopped application did not retain exactly one copy of the selected original"
    return matching[0]


def _accepted_original(j, key, before, digest):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import ApiIdempotencyKey, Expense
    from app.services.original_read_service import read_original_snapshot

    after = j.facts()
    assert after["row_version"] == before["row_version"] + 1
    assert after["image_hash"] == digest and after["original_attached"]
    assert all(after[name] == value for name, value in before.items()
        if name not in {"row_version", "image_hash", "original_attached"}), "Adding an original changed financial facts"
    with SessionLocal() as db:
        receipts = db.scalars(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.tenant_id == j.fixture.ledger_id,
            ApiIdempotencyKey.operation == "attach_original")).all()
        assert len(receipts) == 1 and receipts[0].idempotency_key == key
        assert receipts[0].status == "succeeded" and receipts[0].target_id == str(before["id"])
        expense = db.get(Expense, before["id"])
        with read_original_snapshot(relative_path=expense.image_path, tenant_id=j.fixture.ledger_id,
                expected_sha256=digest) as original:
            assert hashlib.sha256(original.path.read_bytes()).hexdigest() == digest


def native_first_original(j):
    native, before = j.native, j.facts()
    source = j.evidence / "financial-selected-original.png"
    digest = synthetic_receipt(source, amount="12.34", date_text=before["date"])
    device_path = "/sdcard/Download/financial-selected-original.png"
    native.adb("push", str(source), device_path)
    native.adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", "file://" + device_path)
    native.click("原件", stable=True)
    native.click("添加小票或截图", stable=True)
    _pick_original(native)
    native.reveal_any("financial-selected-original.png")
    review = "这是这笔账单对应的原件"
    native.set_switch(review, True)
    native.capture("financial-original-selection-before-cold-stop")
    assert j.facts() == before, "Choosing and reviewing an image published it before confirmation"
    old_pid = native.adb("shell", "pidof", "com.ticketbox").strip()
    assert old_pid
    native.adb("shell", "am", "force-stop", "com.ticketbox")
    assert not any(line.split()[-1:] == ["com.ticketbox"] for line in native.adb(
        "shell", "ps", "-A", "-o", "PID,NAME").splitlines()), "The original app process is still running"
    key = _retained_key(native, digest)

    # Change the original provider file while the app is gone. Recovery must use
    # the bytes accepted before the stop, not reopen that now-different source.
    changed = j.evidence / "financial-provider-changed.png"
    assert synthetic_receipt(changed, amount="99.99", date_text=before["date"]) != digest
    native.adb("push", str(changed), device_path)
    native.restart()
    assert native.adb("shell", "pidof", "com.ticketbox").strip() != old_pid
    j.native_open()
    # The retained selection opens its panel; toggling the header would hide it.
    native.reveal_any("financial-selected-original.png")
    native.capture("financial-original-selection-after-cold-restart")
    native.reveal_any(review)
    checks = [node for node in native.tree().iter("node") if node.attrib.get("checkable") == "true"
        and any(review == part.attrib.get("text") for part in node.iter("node"))]
    assert len(checks) == 1 and checks[0].attrib.get("checked") == "false", "Restored evidence needs a fresh human confirmation"
    assert j.facts() == before, "Cold restoration published the unsubmitted original"
    native.set_switch(review, True)
    native.click("确认并保存原件", stable=True)
    j.expect(lambda value: value["original_attached"], "The restored original did not reach the existing bill")
    _accepted_original(j, key, before, digest)
    native.reveal_any("服务端已接受")
    native.capture("financial-original-first-accepted")
    j.native_open()
    return digest
