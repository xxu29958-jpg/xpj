"""Audit lane — 三端设计 token parity(/web ↔ Android)。

强约束:`/web` 的 `tokens.css` 与 Android 的 Kotlin token 源是同一套调色板的镜像;
此前只靠人自觉,`scripts/` 下无任何检查在拦——改一处忘另一处即静默漂移(/web 与
Android 视觉分叉)。本 lane 把它变成硬检查,逐主题(paper/mono/midnight)比对。

校验:
  - `tokens.css` ↔ `ThemeVisuals.kt`:brand / surface / text 共 12 个不透明核心 token
  - `tokens.css` ↔ `StateTokens.kt`:success/warn/danger/info/neutral 的 **fg**(状态文字色)

不校验:
  - `Theme.kt` 的 Material `colorScheme` —— 它现在从 `ThemeVisuals`/`StateTokens`
    **派生**(单一真相源),结构上不可能漂,无需也无法按字面比对。
  - state 的 bg/border —— midnight 端 /web 用半透明叠加、Android 预合成为不透明,
    属刻意分叉,比对会误报。
  - chart / goal / card 子调色板 —— 留待后续扩展。

只比对不透明值(`#rrggbb` ↔ `Color(0xFFrrggbb)`),避开 alpha 取整歧义。
由 `release_audit.py` 自动发现并以子进程运行(cwd=backend);退出码 0=PASS。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_TOKENS_CSS = _BACKEND / "app" / "static" / "shared" / "tokens.css"
_DESIGN = _REPO / "android" / "app" / "src" / "main" / "java" / "com" / "ticketbox" / "ui" / "design"
_THEME_VISUALS = _DESIGN / "ThemeVisuals.kt"
_STATE_TOKENS = _DESIGN / "StateTokens.kt"

_THEMES = ("paper", "mono", "midnight")

# tokens.css 核心 token ↔ ThemeVisuals 字段(不透明,逐主题须一致)
_CORE_MAPPING: tuple[tuple[str, str], ...] = (
    ("--brand-primary", "primary"),
    ("--brand-primary-strong", "primaryDark"),
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

_VISUALS_ANCHOR = {t: f"AppSkin.{t.capitalize()} -> ThemeVisuals(" for t in _THEMES}
_STATE_ANCHOR = {t: f"AppSkin.{t.capitalize()} -> StateTokens(" for t in _THEMES}


def _balanced_block(text: str, start: int, open_ch: str, close_ch: str) -> str:
    """从 ``start`` 起第一个 ``open_ch`` 开始,返回括号配平的整段(含括号)。"""
    i = text.index(open_ch, start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_ch:
            depth += 1
        elif text[j] == close_ch:
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    raise ValueError(f"unbalanced block from offset {i}")


def _norm_argb(argb: str) -> str:
    """``0xAARRGGBB`` → 不透明时 'rrggbb',否则 'aarrggbb'(小写)。"""
    argb = argb.lower()
    return argb[2:] if argb.startswith("ff") else argb


def _css_theme_values(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for theme in _THEMES:
        block = _balanced_block(text, text.index(f'[data-theme="{theme}"]'), "{", "}")
        out[theme] = {
            f"--{m.group(1)}": m.group(2).lstrip("#").lower()
            for m in re.finditer(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})", block)
        }
    return out


def _kotlin_field_values(text: str, anchors: dict[str, str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for theme, anchor in anchors.items():
        block = _balanced_block(text, text.index(anchor), "(", ")")
        out[theme] = {
            m.group(1): _norm_argb(m.group(2))
            for m in re.finditer(r"(\w+)\s*=\s*Color\(0x([0-9A-Fa-f]{8})\)", block)
        }
    return out


def _kotlin_state_fg(text: str, anchors: dict[str, str]) -> dict[str, dict[str, str]]:
    """StateTone(bg, fg, border) → 取 fg(第 2 个 Color),逐 tone。"""
    out: dict[str, dict[str, str]] = {}
    for theme, anchor in anchors.items():
        block = _balanced_block(text, text.index(anchor), "(", ")")
        tones: dict[str, str] = {}
        for line in block.splitlines():
            head = re.match(r"\s*(\w+)\s*=\s*StateTone\(", line)
            cols = re.findall(r"Color\(0x([0-9A-Fa-f]{8})\)", line)
            if head and len(cols) == 3:
                tones[head.group(1)] = _norm_argb(cols[1])
        out[theme] = tones
    return out


def _diff(theme: str, label: str, want: str | None, got: str | None, source: str) -> str | None:
    if want is None or got is None:
        return f"[{theme}] {label} 缺(css={want} {source}={got})"
    if want != got:
        return f"[{theme}] {label}: tokens=#{want} ≠ {source}=#{got}"
    return None


def main() -> int:
    # Windows 控制台/管道默认 cp936(GBK),无法编码 ↔ 等符号;强制 UTF-8(CI 同为 Windows)。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    css = _css_theme_values(_TOKENS_CSS.read_text(encoding="utf-8"))
    visuals = _kotlin_field_values(_THEME_VISUALS.read_text(encoding="utf-8"), _VISUALS_ANCHOR)
    state_fg = _kotlin_state_fg(_STATE_TOKENS.read_text(encoding="utf-8"), _STATE_ANCHOR)

    problems: list[str] = []
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

    print(
        f"== 三端 token parity（{checked} 项 · {len(_CORE_MAPPING)} 核心 + "
        f"{len(_STATE_TONES)} state-fg × {len(_THEMES)} 主题）=="
    )
    if problems:
        print(f"FAIL: 发现 {len(problems)} 处三端 token 漂移:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: tokens.css ↔ ThemeVisuals.kt / StateTokens.kt 逐主题一致(Theme.kt 已派生,无需比对)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
