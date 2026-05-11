"""Merchant normalization helpers (v0.4-alpha3 slice 2 / M3 / T10).

First version is intentionally conservative:

* trim outer whitespace
* fold ASCII case (lowercase) for grouping
* collapse runs of any unicode whitespace into a single ASCII space
* strip a small set of zero-width / BOM characters that sneak in from OCR

We deliberately do **not** create a ``MerchantAlias`` table, do not
overwrite ``Expense.merchant``, and do not run fuzzy matching. The
normalized form is only used as a grouping key for rankings and the
``/web/categories/uncategorized`` summary; the original ``merchant``
string is always preserved on the row.
"""

from __future__ import annotations

import re

# Common zero-width / BOM characters often pasted from screenshots.
_ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u00a0"
_TRANSLATE = {ord(ch): " " for ch in _ZERO_WIDTH}
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


def normalize_merchant(raw: str | None) -> str:
    """Return the normalized merchant key for grouping.

    Returns ``""`` for ``None`` / blank input so callers can decide whether
    the row counts as "no merchant" without a second ``is None`` check.
    """
    if raw is None:
        return ""
    cleaned = raw.translate(_TRANSLATE)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return ""
    return cleaned.casefold()


def display_merchant(raw: str | None) -> str:
    """Return a human-friendly merchant string (trim + space-collapse).

    Unlike :func:`normalize_merchant`, this preserves case so the UI keeps
    the user's original casing. Returns ``""`` for blank/None input.
    """
    if raw is None:
        return ""
    cleaned = raw.translate(_TRANSLATE)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned
