#!/usr/bin/env python
"""Android ad-hoc alpha-literal ratchet (A7 / AppAlpha adoption).

Goal: stop the sprawl of magic ``Color.copy(alpha = 0.x)`` / inline
``Color(0xAARRGGBB)`` literals in the **production** Android UI from growing,
and let it shrink as call sites migrate to the semantic
``com.ticketbox.ui.design.AppAlpha`` tiers (faint / subtle / soft / medium /
strong / heavy / opaque). This is a ratchet, not an allowlist: the in-scope
literal count may only go DOWN (or stay equal). Adding a new magic alpha to a
production widget/screen raises the count and fails the lane — use an AppAlpha
tier instead (or migrate one of the existing residuals in the same PR to stay
flat).

This is deliberately NOT a big-bang replacement (the UI/UX upgrade map cut that
approach): AppAlpha.kt only *provides* the tiers + a small demo migration; this
lane freezes the residual and bleeds it down over time.

Scope (production presentation surface only)
--------------------------------------------
Scanned: ``ui/components`` and ``ui/screens`` under ``com/ticketbox``.

Exempt (ART / token-definition layers — custom alpha values are legitimate
there, not a magic-number smell):
  - ``ui/appearance/**``   — appearance + custom-background picker/catalog.
  - ``ui/theme/**``        — theme color/alpha (glass/shadow tints) source.
  - ``ui/design/**``       — design-token + visual definitions, incl.
                             ``AppAlpha.kt`` (the canonical tier anchors live
                             here), ``ThemeVisuals.kt`` / ``BackgroundVisuals.kt``
                             and the ``*Tokens.kt`` color palettes.
  - ``ui/components/ReceiptIllustration.kt``     — hand-drawn illustration art.
  - ``ui/components/ComponentPreviewSamples.kt`` — @Preview-only sample data,
                                                   not shipped UI.
  - ``ui/components/ClearCelebration.kt`` — celebration animation art (the shared
                                            clear/settle confetti body; pending +
                                            member-debt 两清 both forward to it).

What counts as a literal: a numeric alpha in ``.copy(alpha = <number>)`` form,
or an 8-hex ``Color(0x........)`` constructor (carries an explicit alpha byte).
Identifier alphas like ``.copy(alpha = AppAlpha.heavy)`` or
``.copy(alpha = resolvedAlpha)`` do NOT count — that is exactly the migrated /
parameterized shape we want. Comments (line / block / KDoc) are stripped first
so a ``.copy(alpha = 0.5f)`` inside a KDoc example does not inflate the count.

Baseline is the current in-scope actual; lower it in the same diff whenever you
migrate a residual to AppAlpha. Run directly::

    python scripts/_audit_android_alpha_ratchet.py          # check vs baseline
    python scripts/_audit_android_alpha_ratchet.py --list   # per-file breakdown
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Windows consoles default to cp936/cp1252; force UTF-8 (mirrors release_audit).
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "ticketbox"
UI_ROOT = SRC_ROOT / "ui"

# Directories scanned for ad-hoc alpha literals (production presentation only).
SCAN_DIRS = ("components", "screens")

# Art / token-definition layers exempt from the ratchet — see module docstring.
# Stored as ``ui``-relative POSIX paths (dir prefixes end with "/").
EXEMPT_PREFIXES = (
    "appearance/",
    "theme/",
    "design/",
)
EXEMPT_FILES = (
    "components/ReceiptIllustration.kt",
    "components/ComponentPreviewSamples.kt",
    "components/ClearCelebration.kt",
)

# Frozen residual: the in-scope literal count may only ratchet DOWN. Lower this
# in the SAME diff whenever a residual migrates to an AppAlpha tier. Seeded
# 2026-06-12 with the post-(5-site demo) actual; 2026-06-25 lowered 119→117 when
# the mascot empty-state slice deleted LedgerEmptyIllustration (its two ad-hoc
# .copy(alpha=0.14f/0.66f) tints went away with the hand-drawn receipt icon);
# 2026-06-26 lowered 117→116 when CategoryDonut's empty-ring
# Color.LightGray.copy(alpha=0.28f) migrated to the themed ChartTokens.empty token.
BASELINE = 116

# ``.copy(alpha = <number>)`` — number is a decimal/int float literal (optional
# trailing ``f``). Identifier args (AppAlpha.heavy / resolvedAlpha) are NOT
# matched on purpose. ``Color(0x........)`` — 8 hex digits (explicit alpha byte).
ALPHA_COPY_RE = re.compile(r"\.copy\(\s*alpha\s*=\s*[0-9][0-9.]*f?\s*\)")
COLOR_HEX_RE = re.compile(r"Color\(\s*0[xX][0-9A-Fa-f]{8}")


def strip_comments(src: str) -> str:
    """Replace Kotlin line/block/KDoc comments with spaces (length-preserving is
    unnecessary; we only count regex hits afterwards). String literals are left
    intact — an alpha literal is real code wherever it appears outside a comment.

    Flat ``if … continue`` siblings (not an if/elif chain) keep AST block nesting
    shallow, mirroring the codebase nesting-depth gate convention.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _is_exempt(rel_ui: str) -> bool:
    if rel_ui in EXEMPT_FILES:
        return True
    return any(rel_ui.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def count_per_file() -> list[tuple[str, int]]:
    """Return [(ui-relative path, literal count)] for every in-scope file that
    has at least one ad-hoc alpha literal, sorted by path."""
    counts: list[tuple[str, int]] = []
    for sub in SCAN_DIRS:
        root = UI_ROOT / sub
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.kt")):
            rel_ui = path.relative_to(UI_ROOT).as_posix()
            if _is_exempt(rel_ui):
                continue
            code = strip_comments(path.read_text(encoding="utf-8"))
            hits = len(ALPHA_COPY_RE.findall(code)) + len(COLOR_HEX_RE.findall(code))
            if hits:
                counts.append((rel_ui, hits))
    return counts


def main(argv: list[str]) -> int:
    per_file = count_per_file()
    total = sum(count for _, count in per_file)

    if "--list" in argv:
        for rel_ui, count in per_file:
            print(f"  {count:3d}  ui/{rel_ui}")
        print(f"  --- total in-scope ad-hoc alpha literals: {total} (baseline {BASELINE})")
        return 0

    if total > BASELINE:
        print(
            f"FAIL: ad-hoc alpha literals in the production Android UI rose to "
            f"{total} (baseline {BASELINE}). A new magic ``Color.copy(alpha = "
            f"0.x)`` / ``Color(0x..)`` slipped into ui/components or ui/screens. "
            f"Use a semantic com.ticketbox.ui.design.AppAlpha tier (faint / "
            f"subtle / soft / medium / strong / heavy / opaque) instead — or "
            f"migrate an existing residual in the same PR to stay flat. Run "
            f"`--list` for the per-file breakdown."
        )
        return 1

    if total < BASELINE:
        print(
            f"FAIL (ratchet not lowered): in-scope alpha literals dropped to "
            f"{total} but BASELINE is still {BASELINE}. Lower BASELINE to "
            f"{total} in this same diff so the ratchet keeps holding the new "
            f"floor."
        )
        return 1

    print(
        f"PASS: production Android UI ad-hoc alpha literals held at baseline "
        f"{BASELINE} (AppAlpha tiers cover the migrated/new sites)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
