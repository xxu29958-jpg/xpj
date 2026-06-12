"""三端 token parity 比对表(纯数据,**不是** audit lane)。

刻意**不**用 `_audit_` 前缀:`release_audit.py` 自动发现并以子进程跑每个
`_audit_*.py`;本文件只是 `_audit_token_parity.py` import 的数据表,没有 `main()`,
不该被当独立 lane 收割。命名 `_token_parity_tables.py` 既走下划线「私有单一用途」
约定,又避开 lane 发现 glob。

为什么拆出来:`_audit_token_parity.py` 把 ≈230 个 token 的逐字段 mapping 内联会顶破
`_audit_codebase.py` 的 500 行 file-LOC 门(`codebase_audit_gate.files_over_500` 已
满额 14,再涨即 FAIL)。映射表是稳定的「哪个 CSS var ↔ 哪个 Kotlin 字段」声明,与
解析/比对逻辑正交,拆开后两个文件都稳在 500 行内,且表本身就是给人审的「真相清单」。

每张表是扁平 `tuple[(css_var, kotlin_field), ...]`,顺序 = Kotlin data class 字段顺序,
方便逐行目检对账。Kotlin 端的结构化导航(series List、嵌套 data class)由 lane 里
对应的小解析器按这里声明的字段名/分组键完成。

「刻意分叉不比对」沿用 lane 既有规则:
  - Goal 的 bg/border 在 midnight 端 /web 用半透明叠加、Android 预合成不透明,
    属刻意分叉 → 本表只列 GoalTokens 的 **fg**(5 个 tone)。
  - state 的 bg/border 同理(已在 lane 既有 `_STATE_TONES` 处理,本表不重复)。
"""

from __future__ import annotations

# ── ChartTokens(全量)─────────────────────────────────────────────────────
# CSS 端 8 个 --chart-series-N ↔ Kotlin `series: List<Color>` 的第 N 个元素。
# series 单列出来,因为 Kotlin 端是 List 而非具名字段。
CHART_SERIES_VARS: tuple[str, ...] = (
    "--chart-series-1",
    "--chart-series-2",
    "--chart-series-3",
    "--chart-series-4",
    "--chart-series-5",
    "--chart-series-6",
    "--chart-series-7",
    "--chart-series-8",
)

# ChartTokens 其余具名 Color 字段(顺序对齐 data class 声明)。
CHART_FIELD_MAPPING: tuple[tuple[str, str], ...] = (
    ("--chart-sequential-from", "sequentialFrom"),
    ("--chart-sequential-to", "sequentialTo"),
    ("--chart-diverging-negative", "divergingNegative"),
    ("--chart-diverging-zero", "divergingZero"),
    ("--chart-diverging-positive", "divergingPositive"),
    ("--chart-axis", "axis"),
    ("--chart-axis-label", "axisLabel"),
    ("--chart-grid", "grid"),
    ("--chart-grid-emphasis", "gridEmphasis"),
    ("--chart-tooltip-bg", "tooltipBg"),
    ("--chart-tooltip-fg", "tooltipFg"),
    ("--chart-tooltip-border", "tooltipBorder"),
    ("--chart-legend-fg", "legendFg"),
    ("--chart-legend-marker", "legendMarker"),
    ("--chart-sankey-ribbon", "sankeyRibbon"),
    ("--chart-sankey-ribbon-emphasis", "sankeyRibbonEmphasis"),
    ("--chart-overspend", "overspend"),
    ("--chart-empty", "empty"),
)

# ── GoalTokens(仅 fg)──────────────────────────────────────────────────────
# bg/border 刻意分叉(见模块 docstring),只比 fg。
# 表项 = (css_var, goal_state_field):goal_state_field 是 GoalTokens 里的 tone 名,
# lane 取该 tone 的 GoalStateTokens(bg, fg, border) 的第 2 个 Color(fg)。
GOAL_FG_MAPPING: tuple[tuple[str, str], ...] = (
    ("--goal-idle-fg", "idle"),
    ("--goal-on-track-fg", "onTrack"),
    ("--goal-near-limit-fg", "nearLimit"),
    ("--goal-exceeded-fg", "exceeded"),
    ("--goal-expired-fg", "expired"),
)

# ── DashboardCardTokens(全量 24 = 8 卡 × accent/icon/surface)────────────────
# 表项 = (css_accent_var, css_icon_var, css_surface_var, card_field)。
# Kotlin 端 card_field 是 DashboardCardTokens 里的卡名,对应
# DashboardCardAccent(accent, iconTint, surface) 三个 Color,按位对齐三个 css var。
CARD_MAPPING: tuple[tuple[str, str, str, str], ...] = (
    ("--card-pending-accent", "--card-pending-icon", "--card-pending-surface", "pending"),
    ("--card-month-spend-accent", "--card-month-spend-icon", "--card-month-spend-surface", "monthSpend"),
    ("--card-recent-upload-accent", "--card-recent-upload-icon", "--card-recent-upload-surface", "recentUpload"),
    ("--card-recurring-accent", "--card-recurring-icon", "--card-recurring-surface", "recurring"),
    ("--card-goals-accent", "--card-goals-icon", "--card-goals-surface", "goals"),
    ("--card-budget-accent", "--card-budget-icon", "--card-budget-surface", "budget"),
    ("--card-backup-accent", "--card-backup-icon", "--card-backup-surface", "backup"),
    ("--card-device-accent", "--card-device-icon", "--card-device-surface", "device"),
)

# ── SwipeActionTokens(bg/fg × 3;iconTint 不比 —— 见下注)─────────────────────
# 表项 = (css_bg_var, css_fg_var, swipe_field)。Kotlin SwipeAction(bg, fg, iconTint),
# /web 无独立 iconTint token(图标继承 fg 色),故只比 bg/fg 两位,iconTint 不进表。
SWIPE_MAPPING: tuple[tuple[str, str, str], ...] = (
    ("--swipe-confirm-bg", "--swipe-confirm-fg", "confirm"),
    ("--swipe-ignore-bg", "--swipe-ignore-fg", "ignore"),
    ("--swipe-delete-bg", "--swipe-delete-fg", "delete"),
)

# ── SkeletonTokens(base/shine × 3 主题)──────────────────────────────────────
# 表项 = (css_var, skeleton_field)。两端都是半透明,按 half-up alpha 折算后比对。
SKELETON_MAPPING: tuple[tuple[str, str], ...] = (
    ("--skeleton-base-bg", "base"),
    ("--skeleton-shine-bg", "shine"),
)
