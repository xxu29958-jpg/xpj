#!/usr/bin/env python
"""ADR-0044 presentation-copy gate: no NEW hardcoded Chinese in the Android
presentation layer.

Scope (narrow, on purpose — see ADR-0044 + the 2026-06-07 review): only the
production *presentation* surface where user-visible copy lives —
``ui/``, ``viewmodel/`` and ``security/`` under ``com/ticketbox``. The data /
domain / notification / repository layers keep legitimate Chinese (domain
category values, parser keywords, repository error-message fallbacks) and are
NOT scanned here.

How it works: a comment-aware char walker extracts string *literals* (ignoring
``//``, ``/* */``, KDoc, ``${...}`` template expressions and char literals, so
quoted Chinese inside a comment is not flagged). Any literal containing a CJK
char must be registered in ``ALLOWLIST`` (keyed ``"<path> :: <literal>"``) with
a one-line reason. A new, unregistered Chinese literal fails the lane — the
regression net the review asked for ("挡回潮"). Shrink the allowlist over time
as residuals get resourced; do not add the data/domain layers here.

Run directly: ``python scripts/_audit_android_presentation_copy.py``
(release_audit auto-discovers it as a lane). ``--list`` prints every Chinese
literal as a ready-to-paste allowlist key (used to seed/refresh the allowlist).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows consoles default to cp936/cp1252; Chinese literals in the report blow
# up charmap mid-print. Force UTF-8 (mirrors release_audit.py).
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "ticketbox"
SCAN_DIRS = ("ui", "viewmodel", "security")
SEP = " :: "


def has_han(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _skip_quoted(src: str, i: int, n: int, quote: str) -> int:
    """``i`` is just after an opening ``quote``; return the index just after the
    matching close, honoring backslash escapes."""
    while i < n and src[i] != quote:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def _skip_template_expr(src: str, i: int, n: int) -> int:
    """``i`` is just after ``${``; skip the balanced-brace expression (including
    nested strings and char literals) and return the index just after its ``}``."""
    depth = 1
    # Flat `if … continue` siblings (mirrors extract_string_literals): a nested
    # string OR char literal is skipped whole, so a brace/quote inside a `'{'` /
    # `'"'` char literal cannot desync brace-depth tracking and swallow copy that
    # follows the template. Keeps AST nesting shallow for the codebase gate.
    while i < n and depth > 0:
        cc = src[i]
        if cc == '"':
            i = _skip_quoted(src, i + 1, n, '"')
            continue
        if cc == "'":
            i = _skip_quoted(src, i + 1, n, "'")
            continue
        if cc == "{":
            depth += 1
        elif cc == "}":
            depth -= 1
        i += 1
    return i


def _read_string(src: str, i: int, n: int) -> tuple[str, int]:
    """``i`` is just after the opening ``"``; return (content, index after the
    closing ``"``). ``${...}`` templates collapse to a ``${}`` placeholder."""
    buf: list[str] = []
    while i < n:
        ch = src[i]
        if ch == "\\":
            buf.append(src[i:i + 2])
            i += 2
        elif ch == '"':
            i += 1
            break
        elif ch == "$" and i + 1 < n and src[i + 1] == "{":
            i = _skip_template_expr(src, i + 2, n)
            buf.append("${}")
        else:
            buf.append(ch)
            i += 1
    return "".join(buf), i


def extract_string_literals(src: str) -> list[str]:
    """Return the contents of every Kotlin string literal in ``src``, skipping
    line/block/KDoc comments and char literals (so quoted Chinese inside a
    comment is not reported)."""
    literals: list[str] = []
    i, n = 0, len(src)
    # Flat `if … continue` siblings (not an if/elif chain) so AST block nesting
    # stays at depth 2 — an elif chain nests in each `orelse` and trips the
    # codebase nesting-depth gate.
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if src.startswith('"""', i):
            j = src.find('"""', i + 3)
            end = n if j == -1 else j
            literals.append(src[i + 3:end])
            i = n if j == -1 else j + 3
            continue
        if c == '"':
            content, i = _read_string(src, i + 1, n)
            literals.append(content)
            continue
        if c == "'":
            i = _skip_quoted(src, i + 1, n, "'")
            continue
        i += 1
    return literals


def scan() -> list[tuple[str, str]]:
    """Return [(repo-relative path, Chinese literal)] across the scanned dirs."""
    hits: list[tuple[str, str]] = []
    for sub in SCAN_DIRS:
        root = SRC_ROOT / sub
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.kt")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for lit in extract_string_literals(path.read_text(encoding="utf-8")):
                if has_han(lit):
                    hits.append((rel, lit))
    return hits


# Allowlisted Chinese literals that legitimately stay in the presentation layer.
# Key: "<repo-relative path> :: <literal text>". Value: one-line reason carrying
# a reviewed-invariant keyword (static / preview / internal / no data surface).
# A Chinese literal not listed here fails the lane. Categories: static catalog /
# preview sample / static formatter / internal keyword-match / no-data-surface
# tail / static fallback-default / static appearance label (ratchet-candidate).
# Shrink this over time; do NOT add the data/domain layers.
ALLOWLIST: dict[str, str] = {
    "android/app/src/main/java/com/ticketbox/ui/appearance/AppearanceDefaults.kt :: 跟随主题": "static appearance source label; ratchet-candidate residual",
    "android/app/src/main/java/com/ticketbox/ui/appearance/AppearanceDefaults.kt :: 内置背景": "static appearance source label; ratchet-candidate residual",
    "android/app/src/main/java/com/ticketbox/ui/appearance/AppearanceDefaults.kt :: 自定义图片": "static appearance source label; ratchet-candidate residual",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 自然": "static catalog: built-in background group name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 情绪": "static catalog: built-in background group name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 极简": "static catalog: built-in background group name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 插画": "static catalog: built-in background group name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 纸本": "static catalog: built-in background name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 温润米白与茶铜纸影，和桌面账本默认视觉一致。": "static catalog: built-in background description",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 茶雾": "static catalog: built-in background name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 更明显的暖纸雾面，适合待确认和统计首页。": "static catalog: built-in background description",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 墨白": "static catalog: built-in background name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 冷灰纸面，减少彩色干扰。": "static catalog: built-in background description",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 灰雾": "static catalog: built-in background name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 低对比灰雾，适合表格和长列表。": "static catalog: built-in background description",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 玄夜": "static catalog: built-in background name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 深色玻璃与暖金，适合夜间。": "static catalog: built-in background description",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 暖金": "static catalog: built-in background name",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundCatalog.kt :: 深色底上的暖金光晕，保留暗色但不回到旧蓝绿。": "static catalog: built-in background description",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundPreviewModels.kt :: 待确认": "preview surface label: background preview picker",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundPreviewModels.kt :: 账本": "preview surface label: background preview picker",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundPreviewModels.kt :: 统计": "preview surface label: background preview picker",
    "android/app/src/main/java/com/ticketbox/ui/appearance/BackgroundPreviewModels.kt :: 编辑确认": "preview surface label: background preview picker",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 待确认账单": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 截图上传后不会自动入账": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 等待你确认": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 0 张": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 无待确认": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 识别结果只是草稿": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 还没有待确认账单": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 截图上传后不会自动入账，你确认后才会记录。": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 餐饮": "preview sample data, not shipped UI (category example)",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 上传截图": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 刷新": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 外观与主题": "preview sample data, not shipped UI",
    "android/app/src/main/java/com/ticketbox/ui/components/ComponentPreviewSamples.kt :: 主题皮肤、自定义背景、沉浸强度": "preview sample data, not shipped UI",
    # bottom-nav preview 标签已改走 stringResource(R.string.nav_tab_*),不再硬编码——allowlist 缩 4 条。
    "android/app/src/main/java/com/ticketbox/ui/components/DuplicateNotice.kt :: 图片 hash": "internal keyword match on server duplicate-reason",
    "android/app/src/main/java/com/ticketbox/ui/components/DuplicateNotice.kt :: 金额": "internal keyword match on server duplicate-reason",
    "android/app/src/main/java/com/ticketbox/ui/components/DuplicateNotice.kt :: 商家": "internal keyword match on server duplicate-reason",
    "android/app/src/main/java/com/ticketbox/ui/components/DuplicateNotice.kt :: 时间": "internal keyword match on server duplicate-reason",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt :: 待填写金额": "static formatter: null-amount fallback display",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt :: 汇率待同步": "static formatter: pending-rate fallback display",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt ::  · 汇率 1 ": "static formatter: exchange-rate line assembly",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt :: 未填写时间": "static formatter: blank-time fallback display",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt :: 未设置": "static formatter: blank-date fallback display",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt :: yyyy年M月d日": "static formatter: date pattern",
    "android/app/src/main/java/com/ticketbox/ui/components/Formatters.kt :: yyyy年M月d日 HH:mm": "static formatter: date-time pattern",
    "android/app/src/main/java/com/ticketbox/ui/components/MonthPicker.kt :: ${}年${}月": "static formatter: year-month label",
    "android/app/src/main/java/com/ticketbox/ui/screens/LedgerGrouping.kt :: M月d日 E": "static formatter: date-group pattern",
    "android/app/src/main/java/com/ticketbox/ui/screens/stats/ReportsInsightChartModels.kt :: ${}¥${}万": "static formatter: amount 万 (ten-thousand) unit",
    "android/app/src/main/java/com/ticketbox/ui/screens/stats/StatsMetricGrid.kt :: AI订阅": "internal domain-category match (DefaultCategories value)",
    "android/app/src/main/java/com/ticketbox/ui/screens/stats/StatsMetricGrid.kt :: AI 订阅": "internal domain-category match (spaced legacy variant)",
    "android/app/src/main/java/com/ticketbox/viewmodel/ExpenseEditViewModelItemsEditor.kt :: 未命名": "static fallback-default item name value",
    "android/app/src/main/java/com/ticketbox/viewmodel/ExpenseEditViewModelSplitsEditor.kt :: 未命名成员": "static fallback-default split member name value",
}


def main(argv: list[str]) -> int:
    hits = scan()
    if "--list" in argv:
        for rel, lit in hits:
            print(f'    "{rel}{SEP}{lit}": "",')
        return 0

    present = {f"{rel}{SEP}{lit}" for rel, lit in hits}
    offenders = [(rel, lit) for rel, lit in hits if f"{rel}{SEP}{lit}" not in ALLOWLIST]
    stale = [key for key in ALLOWLIST if key not in present]

    if stale:
        print("WARN: stale allowlist entries (literal gone — trim the allowlist):")
        for key in stale:
            print(f"  {key}")

    if offenders:
        print(
            "FAIL: new hardcoded Chinese in the Android presentation layer "
            "(ui/ viewmodel/ security/). Resource it (stringResource / UiText / "
            "*.getString), or — if it is a legitimate residual (catalog / preview "
            "/ formatter / parser keyword / domain value) — register it in "
            "ALLOWLIST with a one-line reason. See ADR-0044."
        )
        for rel, lit in offenders:
            print(f'  {rel}{SEP}{lit!r}')
        return 1

    print(f"PASS: presentation layer has no unregistered Chinese literals "
          f"({len(ALLOWLIST)} allowlisted residuals).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
