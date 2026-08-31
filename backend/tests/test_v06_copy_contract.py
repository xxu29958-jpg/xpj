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

# A3: 固定支出从「候选优先」升级为「手动注册 + 候选辅助发现」。Web 与 Android
# 各自落地同一 IA —— 主 CTA「添加固定支出」、hero「每月固定支出」、诚实边界
# 「不会自动入账」；候选在两端都不是一键确认主路径。跨端契约只钉这些共享语义,
# 不再钉逐字整句 (两端语气/句式合法分化)。
HONESTY_COPY = "不会自动入账"
ADD_CTA_COPY = "添加固定支出"
HERO_LABEL_COPY = "每月固定支出"
WEB_CANDIDATE_TITLE = "发现的建议"
ANDROID_CANDIDATE_TITLE = "固定支出候选（未确认）"
ANDROID_CANDIDATE_ACTION = "采用建议"


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
    # A3: recurring.html 与 Android 各自落地「手动注册 + 候选辅助发现」IA;
    # 跨端契约钉共享语义 (主 CTA / hero 标签 / 诚实边界 / 候选非一键确认)。
    recurring_web = _read("backend/app/templates/web/recurring.html")
    owner_index = _read("backend/app/templates/owner/index.html")
    android_copy = _android_copy()

    for surface in (recurring_web, android_copy):
        assert ADD_CTA_COPY in surface
        assert HERO_LABEL_COPY in surface
        assert HONESTY_COPY in surface

    # 候选是辅助发现, 不是一键确认主路径 (两端各自的落地措辞)。
    assert WEB_CANDIDATE_TITLE in recurring_web
    assert ANDROID_CANDIDATE_TITLE in android_copy
    assert ANDROID_CANDIDATE_ACTION in android_copy

    assert "正式固定支出只做提醒和对比，不会自动入账" in owner_index
    assert "不上传通知原文" in owner_index


def test_recurring_anomaly_copy_stays_consistent() -> None:
    # stats_web 随 UI/UX 批 14 删除;「本月偏高」异常文案仍由 web_recurring 路由
    # (/web/recurring) 与 android 守护。A3 职责拆分后文案落在 presenter 模块。
    web_recurring_route = _read("backend/app/routes/web_recurring.py")
    web_recurring_presenter = _read("backend/app/routes/_web_recurring_presenter.py")
    android_copy = _android_copy()

    assert "本月偏高" in web_recurring_route + web_recurring_presenter
    assert "本月偏高" in android_copy


def test_notification_privacy_copy_contract() -> None:
    android_copy = _android_copy()
    owner_index = _read("backend/app/templates/owner/index.html")

    assert "通知只生成待确认草稿或本机提醒，核对后才会入账。" in android_copy
    assert "系统授权" in android_copy
    assert "通知原文不会上传到小票夹服务。" in android_copy
    assert "只上传来源、金额、商家、分类和时间" in android_copy
    assert "Android 通知草稿只上传结构化字段，不上传通知原文。" in owner_index


def test_budget_remaining_copy_is_honest_across_web_and_android() -> None:
    """remaining 是「预算剩余」，不是扣完固定与预留后的 safe-to-spend。"""
    budgets_web = _read("backend/app/templates/web/budgets.html")
    android_copy = _android_copy()

    assert "本月预算剩余" in budgets_web
    assert "本月预算剩余" in android_copy
    assert "预算剩余 %1$s" in android_copy
    assert "本月还可用" not in android_copy
    assert "还可花 %1$s" not in android_copy
