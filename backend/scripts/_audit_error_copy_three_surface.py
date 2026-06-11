"""Read-only audit: error-code copy must agree across its three surfaces.

The 2026-06-11 #41 team review flagged that the user-facing copy for backend
error codes lives in FOUR stores with zero machine reconciliation: the backend
table (``app/errors.py::ERROR_MESSAGES``), the Android data layer
(``_RepositorySupport.kt::backendErrorUserMessage`` hardcoded arms), the
Android presentation layer (``ErrorUiText.kt`` arms -> ``R.string.error_*`` ->
``strings.xml``), and the docs table (``docs/rules/ERROR_MESSAGE_MAPPING.md``).
Drift was found the manual way (three sections documented copy no surface
ships). This lane pins the cross-surface contract:

- C1  every ``ErrorUiText`` arm code is an ``ERROR_MESSAGES`` code
- C2  the arm's resource is named ``error_<code>`` (no cross-wiring)
- C3  the referenced resource exists in ``strings.xml``
- C4  every ``error_*`` resource is consumed by an arm (or allowlisted)
- C5  every repository-table arm code is an ``ERROR_MESSAGES`` code
- C6  repository-table copy == ``strings.xml`` copy, verbatim
- C7  codes mapped ONLY in ``ErrorUiText``: ``strings.xml`` == backend message
- C8  every doc ``###`` section is a code the backend can emit
- C9  doc 用户文案 == ``strings.xml`` copy (or backend message when the code
      has no resource); codes whose only backend message is per-request
      dynamic (the ``/u`` throttle pair) have no static truth and are skipped
- C10 every ``ErrorUiText`` code has a doc section (gaps are allowlisted
      ratchet-candidates — backfill the doc, then trim the allowlist)

Anti-vacuity: every parser has a floor (``FLOORS``); a parser drifting off its
source (function renamed, table moved) fails the lane instead of passing on an
empty set. Kotlin sources are comment-stripped first so a dead arm quoted in a
comment never enters the parsed tables.

Run from anywhere::

    backend/.venv/Scripts/python.exe backend/scripts/_audit_error_copy_three_surface.py

Exit 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

# Windows consoles default to cp936/cp1252; Chinese copy in the report blows
# up charmap mid-print. Force UTF-8 (mirrors release_audit.py); guarded so a
# capture stream without reconfigure (pytest) keeps working.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "backend" / "app"
ERRORS_FILE = REPO_ROOT / "backend" / "app" / "errors.py"
STRINGS_XML = REPO_ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"
ERROR_UITEXT_KT = (
    REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "ticketbox" / "viewmodel" / "ErrorUiText.kt"
)
REPO_SUPPORT_KT = (
    REPO_ROOT
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "ticketbox"
    / "data"
    / "repository"
    / "_RepositorySupport.kt"
)
MAPPING_MD = REPO_ROOT / "docs" / "rules" / "ERROR_MESSAGE_MAPPING.md"

UITEXT_FUNCTION = "fun errorCodeStringRes"
REPO_FUNCTION = "fun backendErrorUserMessage"

# Parser floors (anti-vacuity). Actuals at authoring time: 81 backend codes /
# 44 error_* resources / 43 ErrorUiText arms / 35 repository arms / 29 doc
# sections. Floors sit well below so routine additions/removals never touch
# them; only a parser losing its source trips one.
FLOORS: dict[str, int] = {
    "backend": 60,
    "strings": 30,
    "uitext": 30,
    "repo": 20,
    "doc": 20,
}

UITEXT_ARM_RX = re.compile(r'"([a-z0-9_]+)"\s*->\s*R\.string\.([A-Za-z0-9_]+)')
REPO_ARM_RX = re.compile(r'"([a-z0-9_]+)"\s*->\s*"([^"\n]*)"')
DOC_SECTION_RX = re.compile(r"^### ([a-z_]+)\s*$", re.MULTILINE)
DOC_COPY_RX = re.compile(r"^\| 用户文案 \| (.+?) \|\s*$", re.MULTILINE)

# Reviewed gaps. Two key namespaces, both flat {str: str}:
# - a strings.xml resource name (C4): consumed outside the arm mapping;
# - a backend error code (C10): Android-mapped code whose doc section is not
#   written yet. Copy parity is already machine-pinned (C6 repository ==
#   strings.xml), only the doc narrative is missing — backfill the section in
#   ERROR_MESSAGE_MAPPING.md, then trim the entry (stale entries WARN below).
ALLOWLIST: dict[str, str] = {
    "error_generic": "static fallback resource consumed by toUiText(fallback) default, not an arm mapping",
    "amount_invalid": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "currency_not_supported": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "exchange_rate_required": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "exchange_rate_invalid": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "exchange_rate_base_currency": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "permission_denied": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "merchant_alias_not_found": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "merchant_alias_conflict": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "tag_not_found": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "tag_conflict": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "tag_undo_not_found": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "recurring_candidate_not_found": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "recurring_item_not_found": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "recurring_frequency_invalid": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "recurring_status_invalid": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "recurring_item_archived": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
    "notification_source_invalid": "covered by strings.xml verbatim parity (C6); doc backfill ratchet-candidate",
}


def _backend_error_table() -> dict[str, str]:
    """``ERROR_MESSAGES`` {code: message} from errors.py (AST, so a stray
    same-named string elsewhere can't pollute the table)."""
    tree = ast.parse(ERRORS_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        is_table_assign = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ERROR_MESSAGES" for t in node.targets
        )
        if not (is_table_assign and isinstance(node.value, ast.Dict)):
            continue
        table: dict[str, str] = {}
        for key, value in zip(node.value.keys, node.value.values, strict=False):
            is_pair = (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            )
            if is_pair:
                table[key.value] = value.value
        return table
    raise SystemExit("ERROR_MESSAGES dict literal not found in app/errors.py")


def _emitted_apperror_codes() -> set[str]:
    """Every string-literal first arg of an ``AppError(...)`` call across
    backend/app — covers explicit-message codes that never enter
    ``ERROR_MESSAGES`` (e.g. the /u upload-surface throttle pair), so a doc
    section for them is not a ghost (C8)."""
    codes: set[str] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "AppError":
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                codes.add(first.value)
    return codes


def _strings_xml_error_entries() -> dict[str, str]:
    """{resource name: copy} for every ``error_*`` <string> in strings.xml."""
    root = ElementTree.fromstring(STRINGS_XML.read_text(encoding="utf-8"))
    entries: dict[str, str] = {}
    for element in root.iter("string"):
        name = element.get("name", "")
        if name.startswith("error_"):
            entries[name] = "".join(element.itertext())
    return entries


def _kt_skip_quoted(src: str, i: int, n: int) -> int:
    """``i`` is just after an opening quote; return the index just after the
    matching close, honoring backslash escapes."""
    quote = src[i - 1]
    while i < n and src[i] != quote:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def strip_kotlin_comments(src: str) -> str:
    """Drop ``//`` and ``/* */`` comment text (keeping the line break) so a
    dead arm quoted in a comment never enters the parsed tables; string and
    char literals pass through verbatim. Flat ``if … continue`` siblings keep
    AST nesting shallow for the codebase gate."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if src.startswith('"""', i):
            j = src.find('"""', i + 3)
            end = n if j == -1 else j + 3
            out.append(src[i:end])
            i = end
            continue
        if src[i] in {'"', "'"}:
            j = _kt_skip_quoted(src, i + 1, n)
            out.append(src[i:j])
            i = j
            continue
        out.append(src[i])
        i += 1
    return "".join(out)


def _function_slice(path: Path, header: str) -> str:
    """Comment-stripped text of the top-level function declared by ``header``,
    ending at the first column-0 closing brace. A missing header yields an
    empty slice -> zero arms -> the floor fails (never silently green)."""
    src = strip_kotlin_comments(path.read_text(encoding="utf-8"))
    start = src.find(header)
    if start == -1:
        return ""
    end = src.find("\n}", start)
    return src[start:end] if end != -1 else src[start:]


def _uitext_arms() -> dict[str, str]:
    """{code: resource name} from the ``errorCodeStringRes`` when-arms."""
    return dict(UITEXT_ARM_RX.findall(_function_slice(ERROR_UITEXT_KT, UITEXT_FUNCTION)))


def _repo_arms() -> dict[str, str]:
    """{code: copy} from the ``backendErrorUserMessage`` when-arms."""
    return dict(REPO_ARM_RX.findall(_function_slice(REPO_SUPPORT_KT, REPO_FUNCTION)))


def _doc_sections() -> dict[str, str | None]:
    """{code: first 用户文案 cell} per ``### code`` section of the mapping doc
    (None when a section carries no copy row)."""
    text = MAPPING_MD.read_text(encoding="utf-8")
    headers = list(DOC_SECTION_RX.finditer(text))
    sections: dict[str, str | None] = {}
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        copy = DOC_COPY_RX.search(text[match.end():end])
        sections[match.group(1)] = copy.group(1).strip() if copy else None
    return sections


def _floor_failures(counts: dict[str, int]) -> list[str]:
    return [
        f"floor: the {name} parser produced {counts[name]} entries (< {minimum}) — "
        "it drifted off its source; refusing to pass vacuously"
        for name, minimum in FLOORS.items()
        if counts[name] < minimum
    ]


def _uitext_failures(backend: dict[str, str], strings: dict[str, str], uitext: dict[str, str]) -> list[str]:
    out: list[str] = []
    for code, resource in uitext.items():
        if code not in backend:
            out.append(f'C1 ErrorUiText maps "{code}" but it is not an ERROR_MESSAGES code (ghost code)')
        if resource != f"error_{code}":
            out.append(f'C2 ErrorUiText arm "{code}" -> R.string.{resource} is cross-wired (expected error_{code})')
        if resource not in strings:
            out.append(f"C3 ErrorUiText references R.string.{resource} but strings.xml has no such resource")
    return out


def _resource_failures(strings: dict[str, str], uitext: dict[str, str]) -> list[str]:
    referenced = set(uitext.values())
    return [
        f'C4 strings.xml resource "{name}" is not referenced by any ErrorUiText arm and not allowlisted'
        for name in strings
        if name not in referenced and name not in ALLOWLIST
    ]


def _repo_failures(backend: dict[str, str], strings: dict[str, str], repo: dict[str, str]) -> list[str]:
    out: list[str] = []
    for code, copy in repo.items():
        if code not in backend:
            out.append(f'C5 repository table maps "{code}" but it is not an ERROR_MESSAGES code (ghost code)')
        resource = strings.get(f"error_{code}")
        if resource is None:
            out.append(f'C6 repository copy for "{code}" has no strings.xml error_{code} to mirror')
            continue
        if copy != resource:
            out.append(f'C6 repository copy for "{code}" diverges from strings.xml: repo={copy!r} strings={resource!r}')
    return out


def _uitext_only_failures(
    backend: dict[str, str], strings: dict[str, str], uitext: dict[str, str], repo: dict[str, str]
) -> list[str]:
    out: list[str] = []
    for code in uitext:
        if code in repo or code not in backend:
            continue  # repo-arm copy is pinned by C6; a ghost code already failed C1
        resource = strings.get(f"error_{code}")
        if resource is None:
            continue  # missing resource already failed C3
        if resource != backend[code]:
            out.append(
                f'C7 strings.xml error_{code} diverges from the backend message for "{code}": '
                f"strings={resource!r} backend={backend[code]!r}"
            )
    return out


def _doc_failures(
    backend: dict[str, str], emitted: set[str], strings: dict[str, str], doc: dict[str, str | None]
) -> list[str]:
    out: list[str] = []
    for code, copy in doc.items():
        if code not in backend and code not in emitted:
            out.append(f'C8 doc section "{code}" is not a code the backend can emit (ghost section)')
            continue
        if copy is None:
            out.append(f'C9 doc section "{code}" has no | 用户文案 | row to reconcile')
            continue
        expected = strings.get(f"error_{code}", backend.get(code))
        if expected is None:
            continue  # explicit-message-only backend code (per-request dynamic copy) — no static truth
        if copy != expected:
            out.append(f'C9 doc 用户文案 for "{code}" diverges from the shipped copy: doc={copy!r} shipped={expected!r}')
    return out


def _doc_coverage_failures(uitext: dict[str, str], doc: dict[str, str | None]) -> list[str]:
    return [
        f'C10 ErrorUiText code "{code}" has no ### section in ERROR_MESSAGE_MAPPING.md and is not allowlisted'
        for code in uitext
        if code not in doc and code not in ALLOWLIST
    ]


def _stale_allowlist_keys(strings: dict[str, str], uitext: dict[str, str], doc: dict[str, str | None]) -> list[str]:
    """Allowlist entries whose gap no longer exists (doc section backfilled,
    resource now arm-referenced, or code gone) — trim them."""
    referenced = set(uitext.values())
    stale: list[str] = []
    for key in ALLOWLIST:
        live_resource_gap = key in strings and key not in referenced
        live_doc_gap = key in uitext and key not in doc
        if not (live_resource_gap or live_doc_gap):
            stale.append(key)
    return stale


def main() -> int:
    backend = _backend_error_table()
    emitted = _emitted_apperror_codes()
    strings = _strings_xml_error_entries()
    uitext = _uitext_arms()
    repo = _repo_arms()
    doc = _doc_sections()

    counts = {"backend": len(backend), "strings": len(strings), "uitext": len(uitext),
              "repo": len(repo), "doc": len(doc)}
    failures = _floor_failures(counts)
    if not failures:
        failures += _uitext_failures(backend, strings, uitext)
        failures += _resource_failures(strings, uitext)
        failures += _repo_failures(backend, strings, repo)
        failures += _uitext_only_failures(backend, strings, uitext, repo)
        failures += _doc_failures(backend, emitted, strings, doc)
        failures += _doc_coverage_failures(uitext, doc)
        stale = _stale_allowlist_keys(strings, uitext, doc)
        if stale:
            print("WARN: stale ALLOWLIST entries (gap closed — trim the allowlist):")
            for key in stale:
                print(f"  {key}")

    print("Error-code copy is reconciled across backend / Android / docs:")
    if failures:
        for line in failures:
            print(f"  FAIL  {line}")
    else:
        print(
            f"  OK  ({counts['backend']} backend codes; {counts['uitext']} ErrorUiText arms; "
            f"{counts['repo']} repository arms; {counts['strings']} error_* resources; "
            f"{counts['doc']} doc sections; {len(ALLOWLIST)} allowlisted gaps)"
        )
    ok = not failures
    print(f"\n{'PASS' if ok else 'FAIL'}  error-copy-three-surface")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
