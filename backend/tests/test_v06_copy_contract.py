"""v0.6 user-facing copy contract for recurring and notification safety bounds.

ADR-0044: Android user-facing copy now lives in string resources
(`res/values/strings*.xml`), not inline in the `.kt` screens. This three-surface
contract therefore reads the Android copy from the resource XML, while web /
owner copy stays in their templates / routes.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_VALUES = REPO_ROOT / "android" / "app" / "src" / "main" / "res" / "values"

FORMAL_COPY = "这些是已经手动确认过的固定支出；只做提醒和对比，不会自动入账。"
CANDIDATE_TITLE = "固定支出候选（未确认）"
CANDIDATE_COPY = "根据最近账单识别，仅供参考，不会自动入账；确认后才进入正式固定支出。"
RECURRING_HEADER_COPY = "候选需手动确认；正式记录只做提醒和对比，不会自动入账。"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _android_copy() -> str:
    """All Android string resources concatenated.

    ADR-0044 moved user-facing copy out of the `.kt` screens into
    `res/values/strings*.xml`; the contract checks the copy wherever it was
    filed, so we read every `strings*.xml` together.
    """
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(ANDROID_VALUES.glob("strings*.xml"))
    )


def test_recurring_copy_contract_across_web_owner_and_android() -> None:
    # UI/UX 批 14: /web/stats 页删除,固定支出表是 /web/recurring 的严格子集,未迁移;
    # 这套固定支出文案契约改由 recurring.html / android 守护(stats_web 已不存在)。
    recurring_web = _read("backend/app/templates/web/recurring.html")
    owner_index = _read("backend/app/templates/owner/index.html")
    android_copy = _android_copy()

    for surface in (recurring_web, android_copy):
        assert RECURRING_HEADER_COPY in surface

    for surface in (recurring_web, android_copy):
        assert FORMAL_COPY in surface
        assert CANDIDATE_TITLE in surface
        assert CANDIDATE_COPY in surface

    assert "正式固定支出只做提醒和对比，不会自动入账" in owner_index
    assert "不上传通知原文" in owner_index


def test_recurring_anomaly_copy_stays_consistent() -> None:
    # stats_web 随 UI/UX 批 14 删除;「本月偏高」异常文案仍由 web_recurring 路由
    # (/web/recurring) 与 android 守护。
    web_recurring_route = _read("backend/app/routes/web_recurring.py")
    android_copy = _android_copy()

    for surface in (web_recurring_route, android_copy):
        assert "本月偏高" in surface


def test_notification_privacy_copy_contract() -> None:
    android_copy = _android_copy()
    owner_index = _read("backend/app/templates/owner/index.html")

    assert "通知只生成待确认草稿或提醒，不会自动入账。" in android_copy
    assert "系统授权" in android_copy
    assert "通知原文不会上传到小票夹服务。" in android_copy
    assert "只上传来源、金额、商家、分类和时间" in android_copy
    assert "Android 通知草稿只上传结构化字段，不上传通知原文。" in owner_index
