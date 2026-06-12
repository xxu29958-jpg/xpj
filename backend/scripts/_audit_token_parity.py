"""Audit lane — 三端设计 token parity(/web ↔ Android)。

强约束:`/web` 的 `tokens.css` 与 Android 的 Kotlin token 源是同一套调色板的镜像;
此前只靠人自觉,`scripts/` 下无任何检查在拦——改一处忘另一处即静默漂移(/web 与
Android 视觉分叉)。本 lane 把它变成硬检查,逐主题(paper/mono/midnight)比对。

覆盖面(2026-06 从 54 项扩到 ~230,把整套子调色板纳入机器守护):
  - core:`tokens.css` ↔ `ThemeVisuals.kt` 13 个 brand/surface/text token
    (含半透明的 `--brand-primary-bg`,midnight 端为 rgba)。
  - state-fg:`tokens.css` ↔ `StateTokens.kt` 5 个 tone 的 **fg**(状态文字色)。
  - chart:`tokens.css` ↔ `ChartTokens.kt` 全量(series×8 + sequential/diverging +
    axis/grid + tooltip/legend + sankey + overspend/empty)。
  - goal-fg:`tokens.css` ↔ `GoalTokens.kt` 5 个 tone 的 **fg**。
  - card:`tokens.css` ↔ `DashboardCardTokens.kt` 全 24(8 卡 × accent/icon/surface)。
  - swipe:`tokens.css` ↔ `SwipeActionTokens.kt` 的 bg/fg × 3。
  - skeleton:`tokens.css` ↔ `SkeletonTokens.kt` 的 base/shine × 3(半透明)。
  - motion-shimmer:`--motion-shimmer`(ms)↔ `SkeletonTokens.shimmerDurationMillis`
    (Int,ms),数值等值钉(单位两端均为毫秒)。

逐字段 mapping 表拆到 `_token_parity_tables.py`(纯数据,无 `_audit_` 前缀故不被
`release_audit.py` 当独立 lane;拆出是为不顶破 `_audit_codebase.py` 的 500 行 file-LOC
门——`codebase_audit_gate.files_over_500` 已满额)。

不校验(刻意分叉 / 结构上不可能漂):
  - `Theme.kt` 的 Material `colorScheme`:从 `ThemeVisuals`/`StateTokens` **派生**
    (单一真相源),无法也无需按字面比对。
  - state / goal 的 bg/border:midnight 端 /web 用半透明叠加、Android 预合成为不透明,
    属刻意分叉,比对会误报。只比 fg。
  - swipe 的 iconTint:/web 无独立 icon token(图标继承 fg),Kotlin 端 iconTint 现与
    fg 同值,无对照面,不比。

颜色归一化:不透明值比 `rrggbb`(`#rrggbb` ↔ `Color(0xFFrrggbb)`);半透明值比
`aarrggbb`,/web 的 `rgba(r,g,b,a)` 按 **half-up** `int(a×255 + 0.5)` 折算后与 Android
的 `Color(0xAARRGGBB)` 对齐。half-up(非 Python `round` 的 banker's rounding)是因为
Kotlin 端 ARGB 字面量按 half-up 手写:如 `rgba(...,0.30)` → 0.30×255=76.5,half-up=77
=`0x4D`(Kotlin 实写),banker's round 会给 76=`0x4C` 误报漂移(0.70→178.5 同理)。
由 `release_audit.py` 自动发现并以子进程运行(cwd=backend);退出码 0=PASS。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _token_parity_tables import (
    CARD_MAPPING,
    CHART_FIELD_MAPPING,
    CHART_SERIES_VARS,
    GOAL_FG_MAPPING,
    SKELETON_MAPPING,
    SWIPE_MAPPING,
)

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_TOKENS_CSS = _BACKEND / "app" / "static" / "shared" / "tokens.css"
_DESIGN = _REPO / "android" / "app" / "src" / "main" / "java" / "com" / "ticketbox" / "ui" / "design"
_THEME_VISUALS = _DESIGN / "ThemeVisuals.kt"
_STATE_TOKENS = _DESIGN / "StateTokens.kt"
_CHART_TOKENS = _DESIGN / "ChartTokens.kt"
_GOAL_TOKENS = _DESIGN / "GoalTokens.kt"
_CARD_TOKENS = _DESIGN / "DashboardCardTokens.kt"
_SWIPE_TOKENS = _DESIGN / "SwipeActionTokens.kt"
_SKELETON_TOKENS = _DESIGN / "SkeletonTokens.kt"

_THEMES = ("paper", "mono", "midnight")

# tokens.css 核心 token ↔ ThemeVisuals 字段(逐主题须一致;brand-primary-bg 含半透明)
_CORE_MAPPING: tuple[tuple[str, str], ...] = (
    ("--brand-primary", "primary"),
    ("--brand-primary-strong", "primaryDark"),
    ("--brand-primary-bg", "brandPrimaryBg"),
    ("--brand-accent", "accent"),
    ("--surface-app", "backgroundBottom"),
    ("--surface-card", "solidCard"),
    ("--surface-sunken", "surfaceSunken"),
    ("--surface-nav", "surfaceNav"),
    ("--text-default", "textDefault"),
    ("--text-muted", "textMuted"),
    ("--text-meta", "textMeta"),
    ("--text-faint", "textFaint"),
    ("--text-on-primary", "textOnPrimary"),
)

# tokens.css state fg ↔ StateTokens tone(只比 fg;bg/border 在 midnight 刻意分叉)
_STATE_TONES = ("success", "warn", "danger", "info", "neutral")

# Kotlin AppSkin 分支名(data class 工厂里逐主题块的锚点片段)
_SKIN = {"paper": "Paper", "mono": "Mono", "midnight": "Midnight"}

_VISUALS_ANCHOR = {t: f"AppSkin.{t.capitalize()} -> ThemeVisuals(" for t in _THEMES}


def _balanced_block(text: str, start: int, open_ch: str, close_ch: str) -> str:
    """从 ``start`` 起第一个 ``open_ch`` 开始,返回括号配平的整段(含括号)。"""
    i = text.index(open_ch, start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_ch:
            depth += 1
            continue
        if text[j] == close_ch:
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    raise ValueError(f"unbalanced block from offset {i}")


def _skin_block(text: str, skin_name: str) -> str:
    """Kotlin 工厂里 ``AppSkin.<skin_name> -> <Factory>(...)`` 的配平实参段(含外括号)。"""
    anchor = f"AppSkin.{skin_name} ->"
    return _balanced_block(text, text.index(anchor), "(", ")")


def _norm_argb(argb: str) -> str:
    """``0xAARRGGBB`` → 不透明时 'rrggbb',否则 'aarrggbb'(小写)。"""
    argb = argb.lower()
    return argb[2:] if argb.startswith("ff") else argb


_CSS_DECL_RE = re.compile(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))")
_KOTLIN_COLOR_RE = re.compile(r"Color\(0x([0-9A-Fa-f]{8})\)")


def _norm_css_color(raw: str) -> str | None:
    """/web 颜色字面量 → 归一化十六进制,对齐 Android 的 ``0xAARRGGBB`` 约定。

    不透明 → 'rrggbb';半透明 → 'aarrggbb'(alpha 在前,与 ``_norm_argb`` 一致)。
    ``#rgb``/``#rgba`` 简写先展开;``#rrggbbaa``(CSS,alpha 在后)按 Android 顺序重排;
    ``rgba(r,g,b,a)`` 的浮点 alpha 按 **half-up** ``int(a×255 + 0.5)`` 折算(见模块
    docstring:Kotlin 端按 half-up 手写,Python ``round`` 的 banker's rounding 会误报)。
    无法解析 → ``None``(跳过)。
    """
    raw = raw.strip().lower()
    if raw.startswith("#"):
        return _norm_css_hex(raw[1:])
    inner = re.fullmatch(r"rgba?\(([^)]*)\)", raw)
    if not inner:
        return None
    parts = [p.strip() for p in inner.group(1).split(",")]
    if len(parts) not in (3, 4):
        return None
    try:
        # 百分比通道(如 "84%")当前 token 不用,留待需要时再加解析。
        red, green, blue = (int(parts[i]) for i in range(3))
    except ValueError:
        return None
    alpha = int(float(parts[3]) * 255 + 0.5) if len(parts) == 4 else 255
    rgb = f"{red:02x}{green:02x}{blue:02x}"
    return rgb if alpha == 255 else f"{alpha:02x}{rgb}"


def _norm_css_hex(hexes: str) -> str | None:
    """``#`` 后的十六进制位 → 归一化(不透明 'rrggbb' / 半透明 'aarrggbb')。"""
    if len(hexes) in (3, 4):  # #rgb / #rgba 简写 → 每位翻倍
        hexes = "".join(ch * 2 for ch in hexes)
    if len(hexes) == 6:
        return hexes
    if len(hexes) == 8:  # CSS #rrggbbaa → aarrggbb;不透明丢 alpha
        rgb, alpha = hexes[:6], hexes[6:]
        return rgb if alpha == "ff" else alpha + rgb
    return None


def _css_theme_values(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for theme in _THEMES:
        block = _balanced_block(text, text.index(f'[data-theme="{theme}"]'), "{", "}")
        values: dict[str, str] = {}
        for m in _CSS_DECL_RE.finditer(block):
            norm = _norm_css_color(m.group(2))
            if norm is not None:
                values[f"--{m.group(1)}"] = norm
        out[theme] = values
    return out


def _kotlin_field_values(text: str, anchors: dict[str, str]) -> dict[str, dict[str, str]]:
    """逐主题:``field = Color(0x…)`` 平铺字段 → {field: norm_hex}。"""
    out: dict[str, dict[str, str]] = {}
    for theme, anchor in anchors.items():
        block = _balanced_block(text, text.index(anchor), "(", ")")
        out[theme] = {
            m.group(1): _norm_argb(m.group(2))
            for m in re.finditer(r"(\w+)\s*=\s*Color\(0x([0-9A-Fa-f]{8})\)", block)
        }
    return out


def _kotlin_named_tuple_field(text: str, factory: str, tuple_call: str, index: int) -> dict[str, dict[str, str]]:
    """逐主题取形如 ``name = <tuple_call>(c0, c1, c2)`` 的第 ``index`` 个 Color。

    覆盖 GoalTokens(``StateTokens``→取 fg=idx1)、DashboardCardTokens
    (``DashboardCardAccent``)、SwipeActionTokens(``SwipeAction``)这类
    「具名字段 = 三元 Color 构造」结构。返回 {tone_or_card_name: norm_hex}。
    """
    out: dict[str, dict[str, str]] = {}
    for theme, skin_name in _SKIN.items():
        block = _skin_block(text, skin_name)
        found: dict[str, str] = {}
        for line in block.splitlines():
            head = re.match(rf"\s*(\w+)\s*=\s*{re.escape(tuple_call)}\(", line)
            cols = _KOTLIN_COLOR_RE.findall(line)
            if head and len(cols) > index:
                found[head.group(1)] = _norm_argb(cols[index])
        out[theme] = found
    return out


def _kotlin_state_fg(text: str) -> dict[str, dict[str, str]]:
    """StateTokens 工厂里 ``tone = StateTone(bg, fg, border)`` → 取 fg(第 2 个 Color)。"""
    return _kotlin_named_tuple_field(text, "StateTokens", "StateTone", 1)


def _kotlin_series(text: str) -> dict[str, list[str]]:
    """逐主题取 ChartTokens 的 ``series = listOf(...)`` 8 个 Color(按序)。"""
    out: dict[str, list[str]] = {}
    for theme, skin_name in _SKIN.items():
        block = _skin_block(text, skin_name)
        series_block = _balanced_block(block, block.index("series = listOf("), "(", ")")
        out[theme] = [_norm_argb(m) for m in _KOTLIN_COLOR_RE.findall(series_block)]
    return out


def _kotlin_int_const(text: str, name: str) -> int | None:
    """取 ``val/const … <name>: Int = N``(或带默认值的 ``<name>: Int = N``)的 N。"""
    m = re.search(rf"{re.escape(name)}\s*:\s*Int\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def _css_motion_ms(text: str, var: str) -> int | None:
    """取 ``--var: Nms;`` 的整数毫秒。"""
    m = re.search(rf"{re.escape(var)}\s*:\s*(\d+)ms", text)
    return int(m.group(1)) if m else None


def _diff(theme: str, label: str, want: str | None, got: str | None, source: str) -> str | None:
    if want is None or got is None:
        return f"[{theme}] {label} 缺(css={want} {source}={got})"
    if want != got:
        return f"[{theme}] {label}: tokens=#{want} ≠ {source}=#{got}"
    return None


def _check_core_and_state(css, visuals, state_fg, problems: list[str]) -> int:
    checked = 0
    for theme in _THEMES:
        for css_var, field in _CORE_MAPPING:
            msg = _diff(theme, css_var, css[theme].get(css_var), visuals[theme].get(field), f"ThemeVisuals.{field}")
            if msg:
                problems.append(msg)
            checked += 1
        for tone in _STATE_TONES:
            label = f"--state-{tone}-fg"
            msg = _diff(theme, label, css[theme].get(label), state_fg[theme].get(tone), f"StateTokens.{tone}.fg")
            if msg:
                problems.append(msg)
            checked += 1
    return checked


def _check_chart(css, series, fields, problems: list[str]) -> int:
    checked = 0
    for theme in _THEMES:
        for i, css_var in enumerate(CHART_SERIES_VARS):
            got = series[theme][i] if i < len(series[theme]) else None
            msg = _diff(theme, css_var, css[theme].get(css_var), got, f"ChartTokens.series[{i}]")
            if msg:
                problems.append(msg)
            checked += 1
        for css_var, field in CHART_FIELD_MAPPING:
            msg = _diff(theme, css_var, css[theme].get(css_var), fields[theme].get(field), f"ChartTokens.{field}")
            if msg:
                problems.append(msg)
            checked += 1
    return checked


def _check_goal(css, goal_fg, problems: list[str]) -> int:
    checked = 0
    for theme in _THEMES:
        for css_var, tone in GOAL_FG_MAPPING:
            msg = _diff(theme, css_var, css[theme].get(css_var), goal_fg[theme].get(tone), f"GoalTokens.{tone}.fg")
            if msg:
                problems.append(msg)
            checked += 1
    return checked


def _check_card(css, accent, icon, surface, problems: list[str]) -> int:
    checked = 0
    parts = (("accent", accent), ("iconTint", icon), ("surface", surface))
    for theme in _THEMES:
        for accent_var, icon_var, surface_var, card in CARD_MAPPING:
            for css_var, (slot, got_map) in zip((accent_var, icon_var, surface_var), parts, strict=True):
                msg = _diff(theme, css_var, css[theme].get(css_var), got_map[theme].get(card), f"card.{card}.{slot}")
                if msg:
                    problems.append(msg)
                checked += 1
    return checked


def _check_swipe(css, bg, fg, problems: list[str]) -> int:
    checked = 0
    for theme in _THEMES:
        for bg_var, fg_var, action in SWIPE_MAPPING:
            for css_var, slot, got_map in ((bg_var, "bg", bg), (fg_var, "fg", fg)):
                msg = _diff(theme, css_var, css[theme].get(css_var), got_map[theme].get(action), f"swipe.{action}.{slot}")
                if msg:
                    problems.append(msg)
                checked += 1
    return checked


def _check_skeleton(css, skel, problems: list[str]) -> int:
    checked = 0
    for theme in _THEMES:
        for css_var, field in SKELETON_MAPPING:
            msg = _diff(theme, css_var, css[theme].get(css_var), skel[theme].get(field), f"SkeletonTokens.{field}")
            if msg:
                problems.append(msg)
            checked += 1
    return checked


def _check_motion_shimmer(css_text: str, skeleton_text: str, problems: list[str]) -> int:
    """`--motion-shimmer`(ms)↔ SkeletonTokens.shimmerDurationMillis(Int ms)等值钉。"""
    css_ms = _css_motion_ms(css_text, "--motion-shimmer")
    kt_ms = _kotlin_int_const(skeleton_text, "shimmerDurationMillis")
    if css_ms is None or kt_ms is None:
        problems.append(
            f"[scale] --motion-shimmer 数值钉缺(css={css_ms}ms "
            f"SkeletonTokens.shimmerDurationMillis={kt_ms}ms)"
        )
    elif css_ms != kt_ms:
        problems.append(
            f"[scale] shimmer 时长漂移:--motion-shimmer={css_ms}ms ≠ "
            f"SkeletonTokens.shimmerDurationMillis={kt_ms}ms"
        )
    return 1


def main() -> int:
    # Windows 控制台/管道默认 cp936(GBK),无法编码 ↔ 等符号;强制 UTF-8(CI 同为 Windows)。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    css_text = _TOKENS_CSS.read_text(encoding="utf-8")
    visuals_text = _THEME_VISUALS.read_text(encoding="utf-8")
    state_text = _STATE_TOKENS.read_text(encoding="utf-8")
    chart_text = _CHART_TOKENS.read_text(encoding="utf-8")
    goal_text = _GOAL_TOKENS.read_text(encoding="utf-8")
    card_text = _CARD_TOKENS.read_text(encoding="utf-8")
    swipe_text = _SWIPE_TOKENS.read_text(encoding="utf-8")
    skeleton_text = _SKELETON_TOKENS.read_text(encoding="utf-8")

    css = _css_theme_values(css_text)
    visuals = _kotlin_field_values(visuals_text, _VISUALS_ANCHOR)
    state_fg = _kotlin_state_fg(state_text)
    chart_series = _kotlin_series(chart_text)
    chart_fields = _kotlin_field_values(chart_text, {t: f"AppSkin.{_SKIN[t]} -> ChartTokens(" for t in _THEMES})
    goal_fg = _kotlin_named_tuple_field(goal_text, "GoalTokens", "GoalStateTokens", 1)
    card_accent = _kotlin_named_tuple_field(card_text, "DashboardCardTokens", "DashboardCardAccent", 0)
    card_icon = _kotlin_named_tuple_field(card_text, "DashboardCardTokens", "DashboardCardAccent", 1)
    card_surface = _kotlin_named_tuple_field(card_text, "DashboardCardTokens", "DashboardCardAccent", 2)
    swipe_bg = _kotlin_named_tuple_field(swipe_text, "SwipeActionTokens", "SwipeAction", 0)
    swipe_fg = _kotlin_named_tuple_field(swipe_text, "SwipeActionTokens", "SwipeAction", 1)
    skel = _kotlin_field_values(skeleton_text, {t: f"AppSkin.{_SKIN[t]} -> SkeletonTokens(" for t in _THEMES})

    problems: list[str] = []
    checked = 0
    checked += _check_core_and_state(css, visuals, state_fg, problems)
    checked += _check_chart(css, chart_series, chart_fields, problems)
    checked += _check_goal(css, goal_fg, problems)
    checked += _check_card(css, card_accent, card_icon, card_surface, problems)
    checked += _check_swipe(css, swipe_bg, swipe_fg, problems)
    checked += _check_skeleton(css, skel, problems)
    checked += _check_motion_shimmer(css_text, skeleton_text, problems)

    print(f"== 三端 token parity（{checked} 项 · core/state/chart/goal/card/swipe/skeleton + 数值钉，3 主题）==")
    if problems:
        print(f"FAIL: 发现 {len(problems)} 处三端 token 漂移:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: tokens.css ↔ Android design token 源逐主题一致(Theme.kt 已派生,无需比对)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
