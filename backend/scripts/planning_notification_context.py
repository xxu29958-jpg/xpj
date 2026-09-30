"""Original image shares and actual identity changes around system reminders."""

from __future__ import annotations

import hashlib
import re

from scripts.planning_journey_android import wait_for
from scripts.planning_notification_source import SOURCES

BINDING_REFUSAL = "这条提醒属于原来的服务器、账号或账本"
OTHER_LEDGER = "Notification-isolation"


def share_original(journey):
    from PIL import Image, ImageDraw

    path = journey.evidence / "notification-shared-original.png"
    canvas = Image.new("RGB", (800, 600), "white")
    ImageDraw.Draw(canvas).text((40, 40), "ISOLATED NOTIFICATION JOURNEY - ORIGINAL IMAGE", fill="black")
    canvas.save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    native = journey.native
    device_path = "/sdcard/Pictures/notification-shared-original.png"
    native.adb("push", str(path), device_path)
    native.adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", "file://" + device_path)

    def media_id():
        rows = native.adb("shell", "content", "query", "--uri", "content://media/external/images/media", "--projection", "_id:_display_name")
        matches = [re.search(r"_id=(\d+)", row) for row in rows.splitlines() if "_display_name=notification-shared-original.png" in row]
        assert len(matches) <= 1, "The controlled shared original is ambiguous"
        return matches[0].group(1) if matches and matches[0] else None

    uri = "content://media/external/images/media/" + wait_for(media_id, "The actual shared image did not enter MediaStore")
    native.adb("shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "image/png", "-d", uri,
        "--eu", "android.intent.extra.STREAM", uri, "--grant-read-uri-permission", "-n", "com.ticketbox/.MainActivity")
    wait_for(lambda: native.has("重试上传"), "The offline original did not retain its upload retry action", 120)
    native.capture("notification-shared-original-offline")
    return digest


def shared_original_result(journey, digest):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Expense
    from app.services.original_read_service import read_original_snapshot

    with SessionLocal() as db:
        rows = list(db.scalars(select(Expense).where(Expense.tenant_id == journey.fixture.ledger_id, Expense.image_hash == digest)))
        assert len(rows) <= 1, "Returning from another task repeated the original image upload"
        if not rows:
            return None
        row = rows[0]
        with read_original_snapshot(relative_path=row.image_path, tenant_id=row.tenant_id, expected_sha256=digest) as original:
            assert hashlib.sha256(original.path.read_bytes()).hexdigest() == digest
        assert row.status == "pending", "Sharing or a reminder confirmed the original image without review"
        return {"id": row.id, "status": row.status, "sha256": digest}


def identity_changes(journey):
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import Expense, Ledger, RepaymentDraft
    from scripts.planning_journey_roles import _member_code

    native = journey.native
    for sample in (5, 6):
        journey.sources.post(SOURCES[0], sample)
    wait_for(lambda: len(journey.facts()["captures"]) == 4, "The original identity did not retain its final two reminders")
    journey.sources.post(SOURCES[0], 4)
    native.plan_home()
    native.click("打开账户与设置")
    native.click("账本")
    native.reveal_any("账本名称")
    native.fill(OTHER_LEDGER, label="账本名称")
    # The section heading and its action share this label; the action is below.
    native.click("新建账本", bottom=True)
    native.reveal_any("已新建账本")
    native.click_within(OTHER_LEDGER, "切换")
    native.reveal_any(f"已切换到「{OTHER_LEDGER}」")
    journey.tap_notification("60.00", expected=BINDING_REFUSAL)
    native.capture("notification-original-ledger-required")
    with SessionLocal() as db:
        other = db.scalar(select(Ledger).where(Ledger.name == OTHER_LEDGER))
        assert other is not None and other.ledger_id != journey.fixture.ledger_id
        assert db.scalar(select(func.count()).select_from(Expense).where(Expense.tenant_id == other.ledger_id)) == 0
        assert db.scalar(select(func.count()).select_from(RepaymentDraft).where(RepaymentDraft.tenant_id == other.ledger_id)) == 0
    native.back()
    native.click_within("通知原任务验证账本", "切换")
    native.reveal_any("已切换到「通知原任务验证账本」")
    native.plan_home()
    native.click("打开账户与设置")
    native.click("安全与隐私")
    native.click("退出账本")
    native.click("确定退出")
    native.bind(_member_code(journey.fixture.ledger_id, "member"), journey.port)
    journey.tap_notification("61.00", expected=BINDING_REFUSAL)
    native.capture("notification-original-account-required")
    assert sorted(row["amount"] for row in journey.facts()["payments"]) == [7000, 9000]
    assert sorted(row["original"] for row in journey.facts()["captures"] if row["status"] == "pending") == [6000, 6100]
    return {"ledger": "original required", "account": "original required", "retained_pending": 2}
