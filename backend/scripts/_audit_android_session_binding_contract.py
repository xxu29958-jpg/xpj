"""Release gate: session / ledger binding mutations only at sanctioned sites.

Persisted credential writes -- ``serverUrl`` (server binding), the session token
when it accompanies a binding switch, and the ledger identity / active ledger --
change the outbox binding. They MUST happen inside
``OutboxRepository.withBindingTransition`` (or be a same-binding token rotation)
so queued offline mutations can never replay under a new session against the
old ledger's id space.

``LocalLedgerSessionCoordinator`` is the canonical boundary that does this. The
"every binding write goes through the transition" rule was previously enforced
only by developer discipline; this lane turns it into a machine gate. Any call
to ``saveServerUrl`` / ``saveToken`` / ``saveIdentity`` / ``saveActiveLedger``
outside the reason-annotated allowlist fails the build, closing future bypass
paths (mirrors the ``android-outbox-contract`` lane shape;
docs/audits/2026-06-14-known-bugs.md P3 #1).

Scans every shipping source set (``main`` + product-flavor / build-type source
sets such as ``gray`` / ``internal``), keyed by source-set name, so a binding
write added under a flavor root is not invisible to the gate. Unit-test
(``test*``) and instrumented (``androidTest*``) source sets are excluded -- test
call sites are legitimate fixtures, not a production bypass.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_SRC = REPO_ROOT / "android" / "app" / "src"

# Credential-write primitives that mutate the outbox binding (server URL,
# session token, ledger identity, active ledger). ``saveActiveLedger`` has no
# production call site today (the active ledger is set via ``saveIdentity`` in
# the coordinator) but is a real binding setter, so it is gated to catch any
# future bypass that switches ledgers outside a binding transition.
_PRIMITIVES = ("saveServerUrl", "saveToken", "saveIdentity", "saveActiveLedger")

# A call/method-reference to one of the primitives: ``.saveX`` or ``::saveX``.
# Definitions (``fun saveX`` / ``override fun saveX``) have no ``.``/``::`` prefix
# and are intentionally not matched.
_CALL_PATTERN = re.compile(r"(?:\.|::)\s*(" + "|".join(_PRIMITIVES) + r")\b")

# (sourceset/relative-posix-path :: primitive) -> why this site may write
# credentials outside LocalLedgerSessionCoordinator. Each entry is an explicit
# risk-ledger line, validated by the allowlist-reasons meta-audit.
ALLOWLIST = {
    "main/java/com/ticketbox/data/repository/LocalLedgerSessionCoordinator.kt::saveServerUrl":
        "session-level binding boundary: serverUrl writes run inside withBindingTransition",
    "main/java/com/ticketbox/data/repository/LocalLedgerSessionCoordinator.kt::saveToken":
        "session-level binding boundary: token writes run inside withBindingTransition",
    "main/java/com/ticketbox/data/repository/LocalLedgerSessionCoordinator.kt::saveIdentity":
        "session-level binding boundary: identity writes run inside withBindingTransition",
    "main/java/com/ticketbox/MainActivity.kt::saveServerUrl":
        "internal debug-bind path writes inside withBindingTransition (FLAG_DEBUGGABLE only)",
    "main/java/com/ticketbox/MainActivity.kt::saveToken":
        "internal debug-bind path writes inside withBindingTransition (FLAG_DEBUGGABLE only)",
    "main/java/com/ticketbox/data/remote/AuthSessionRefresh.kt::saveToken":
        "session refresh rotates the token within the same binding (no ledger/server change)",
}


def _code_only(src: str) -> str:
    """Blank out comments and string-literal contents, keeping code structure.

    A simple char walker so a primitive name mentioned in a comment or string
    literal is never mistaken for a real call site (and a real call after a
    ``//`` inside a string is never swallowed as a comment).
    """

    out: list[str] = []
    i, n = 0, len(src)
    line_comment = block_comment = string = char = triple = False
    # Flat early-continue guards (no if/elif chain) keep AST nesting shallow.
    while i < n:
        c = src[i]
        two = src[i : i + 2]
        three = src[i : i + 3]
        if line_comment:
            line_comment = c != "\n"
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if block_comment:
            block_comment = two != "*/"
            i += 1 if block_comment else 2
            continue
        if triple:
            triple = three != '"""'
            i += 1 if triple else 3
            continue
        if string or char:
            quote = '"' if string else "'"
            i += 2 if c == "\\" else 1
            if c != "\\" and c == quote:
                string = char = False
            continue
        if two == "//":
            line_comment = True
            i += 2
            continue
        if two == "/*":
            block_comment = True
            i += 2
            continue
        if three == '"""':
            triple = True
            i += 3
            continue
        if c == '"' or c == "'":
            string = c == '"'
            char = c == "'"
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _production_source_roots() -> list[Path]:
    """Shipping source sets under ``android/app/src`` (main + flavors / build
    types). Excludes unit-test (``test*``) and instrumented (``androidTest*``)
    source sets. New flavors are picked up automatically."""

    roots: list[Path] = []
    if not ANDROID_SRC.is_dir():
        return roots
    for entry in sorted(ANDROID_SRC.iterdir()):
        if not entry.is_dir():
            continue
        lower = entry.name.lower()
        if lower.startswith("test") or lower.startswith("androidtest"):
            continue
        roots.append(entry)
    return roots


def _detected_sites() -> set[str]:
    sites: set[str] = set()
    for root in _production_source_roots():
        for path in sorted(root.rglob("*.kt")):
            code = _code_only(path.read_text(encoding="utf-8"))
            primitives = {match.group(1) for match in _CALL_PATTERN.finditer(code)}
            if not primitives:
                continue
            rel = f"{root.name}/{path.relative_to(root).as_posix()}"
            for primitive in primitives:
                sites.add(f"{rel}::{primitive}")
    return sites


def main() -> int:
    if not ANDROID_SRC.is_dir():
        print(f"FAIL: android source root not found: {ANDROID_SRC}")
        return 1

    detected = _detected_sites()
    allowed = set(ALLOWLIST)
    failures: list[str] = []

    for site in sorted(detected - allowed):
        failures.append(
            f"unsanctioned credential write {site} -- route binding mutations "
            "through LocalLedgerSessionCoordinator / withBindingTransition, or "
            "add a reason-annotated ALLOWLIST entry"
        )
    for site in sorted(allowed - detected):
        failures.append(
            f"stale ALLOWLIST entry {site} -- the credential write moved or was "
            "removed; drop the entry so the risk ledger stays honest"
        )

    if failures:
        print("FAIL: session/ledger binding contract drift:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        "PASS: session/ledger binding mutations confined to sanctioned sites "
        f"({len(detected)} credential-write site(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
