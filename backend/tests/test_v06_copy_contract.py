"""v0.6 user-facing copy contract for recurring and notification safety bounds."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORMAL_COPY = "这些是已经手动确认过的固定支出；只做提醒和对比，不会自动入账。"
CANDIDATE_TITLE = "固定支出候选（未确认）"
CANDIDATE_COPY = "根据最近账单识别，仅供参考，不会自动入账；确认后才进入正式固定支出。"
RECURRING_HEADER_COPY = "候选需手动确认；正式记录只做提醒和对比，不会自动入账。"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_recurring_copy_contract_across_web_owner_and_android() -> None:
    recurring_web = _read("backend/app/templates/web/recurring.html")
    stats_web = _read("backend/app/templates/web/stats.html")
    owner_index = _read("backend/app/templates/owner/index.html")
    android_recurring = _read("android/app/src/main/java/com/ticketbox/ui/screens/RecurringScreen.kt")
    android_stats = _read("android/app/src/main/java/com/ticketbox/ui/screens/stats/RecurringCandidatesCard.kt")

    for surface in (recurring_web, android_recurring):
        assert RECURRING_HEADER_COPY in surface

    for surface in (recurring_web, stats_web, android_stats):
        assert FORMAL_COPY in surface
        assert CANDIDATE_TITLE in surface
        assert CANDIDATE_COPY in surface

    assert "正式固定支出只做提醒和对比，不会自动入账" in owner_index
    assert "不上传通知原文" in owner_index


def test_recurring_anomaly_copy_stays_consistent() -> None:
    web_recurring_route = _read("backend/app/routes/web_recurring.py")
    stats_web = _read("backend/app/templates/web/stats.html")
    android_recurring = _read("android/app/src/main/java/com/ticketbox/ui/screens/RecurringScreen.kt")
    android_stats = _read("android/app/src/main/java/com/ticketbox/ui/screens/stats/RecurringCandidatesCard.kt")

    for surface in (web_recurring_route, stats_web, android_recurring, android_stats):
        assert "本月偏高" in surface


def test_notification_privacy_copy_contract() -> None:
    notification_settings = _read(
        "android/app/src/main/java/com/ticketbox/ui/screens/settings/NotificationPreferencesScreen.kt"
    )
    owner_index = _read("backend/app/templates/owner/index.html")

    assert "通知只生成待确认草稿或提醒，不会自动入账。" in notification_settings
    assert "系统授权" in notification_settings
    assert "通知原文不会上传到小票夹服务。" in notification_settings
    assert "只上传来源、金额、商家、分类和时间" in notification_settings
    assert "Android 通知草稿只上传结构化字段，不上传通知原文。" in owner_index
