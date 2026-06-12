"""Release gate: Android outbox enum <-> dispatcher <-> enqueue 3-way consistency.

The offline outbox has three moving parts that must agree, or rows silently
rot in ``FAILED`` on a real device:

* the ``PendingMutationType`` enum (``data/local/PendingMutationType.kt``) — the
  catalogue of replayable mutations;
* the ``OutboxMutationDispatcher`` implementations, registered in
  ``AppContainer.outboxDispatchers`` — the code that turns a queued row back
  into a server call;
* the enqueue call sites in the repositories (``type = PendingMutationType.X``)
  — where each type is actually written into the outbox.

The silent bug this lane catches: a type that is *enqueued* but has no
*registered* dispatcher drains straight to FAILED
(``no_dispatcher_registered:<wire>`` in ``OutboxDrainEngine``) — a shipped,
invisible offline-edit loss. It also fails on a dispatcher class that exists
but is never registered (dead wiring), a registered dispatcher whose type is
never enqueued (unreachable), and any attempt to enqueue the ``Unknown``
fallback. Enum types that are forward-declared for the wire protocol but not
yet wired (see ``PendingMutationType.kt``) are reported, not failed.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_android_outbox_dispatcher_coverage.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_SRC = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "ticketbox"
TYPE_FILE = ANDROID_SRC / "data" / "local" / "PendingMutationType.kt"
APP_CONTAINER = ANDROID_SRC / "AppContainer.kt"

# Dispatcher types intentionally registered before their enqueue call site
# lands (the forward-wiring window). Keep empty when wiring lands atomically;
# an entry here suppresses the "registered but never enqueued" failure for one
# type while still requiring the dispatcher to be registered.
DISPATCHER_WITHOUT_CALLSITE: frozenset[str] = frozenset()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_enum_types(source: str) -> set[str]:
    """Enum constant names (including the ``Unknown`` sentinel)."""
    after = source.split("enum class PendingMutationType", 1)
    if len(after) != 2:
        return set()
    body = after[1].split("companion object", 1)[0]
    return set(re.findall(r"^\s*([A-Za-z]\w*)\(\"", body, re.MULTILINE))


def parse_dispatchers(files: dict[str, str]) -> dict[str, str]:
    """Map ``PendingMutationType`` -> dispatcher class name across impl files."""
    type_re = re.compile(r"override\s+val\s+type\b[^=\n]*=\s*PendingMutationType\.(\w+)")
    class_re = re.compile(r"\bclass\s+(\w+)\b[^{]*:\s*[^{]*\bOutboxMutationDispatcher\b", re.DOTALL)
    out: dict[str, str] = {}
    for _name, source in files.items():
        if "OutboxMutationDispatcher" not in source:
            continue
        type_match = type_re.search(source)
        class_match = class_re.search(source)
        if type_match is None or class_match is None:
            continue
        out[type_match.group(1)] = class_match.group(1)
    return out


def _outbox_dispatchers_block(app_container_source: str) -> str:
    """Return only the ``outboxDispatchers = listOf(...)`` call body."""
    marker = "outboxDispatchers"
    marker_index = app_container_source.find(marker)
    if marker_index < 0:
        return ""

    list_index = app_container_source.find("listOf", marker_index)
    if list_index < 0:
        return ""

    open_index = app_container_source.find("(", list_index)
    if open_index < 0:
        return ""

    depth = 0
    for index in range(open_index, len(app_container_source)):
        char = app_container_source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return app_container_source[open_index + 1 : index]
    return ""


def parse_registered_classes(app_container_source: str) -> set[str]:
    """Dispatcher classes instantiated in ``AppContainer.outboxDispatchers``."""
    block = _outbox_dispatchers_block(app_container_source)
    return set(re.findall(r"(\w+Dispatcher)\s*\(", block))


def parse_enqueues(files: dict[str, str], enum_types: set[str]) -> dict[str, set[str]]:
    """Map enqueued ``PendingMutationType`` -> the files that enqueue it.

    Only ``type = PendingMutationType.X`` assignments where ``X`` is a real
    enum constant count — this excludes the ``fromWire(...)`` companion call
    and the dispatchers' own ``override val type`` declarations.
    """
    out: dict[str, set[str]] = {}
    pattern = re.compile(r"\btype\s*=\s*PendingMutationType\.(\w+)")
    for name, source in files.items():
        for line in source.splitlines():
            if "override val type" in line:
                continue
            for match in pattern.finditer(line):
                constant = match.group(1)
                if constant in enum_types:
                    out.setdefault(constant, set()).add(name)
    return out


def _check_unknown_and_constants(
    enum_types: set[str], dispatcher_map: dict[str, str], enqueue_types: dict[str, set[str]]
) -> list[str]:
    """Unknown must never be wired/enqueued, and every reference is a real constant."""
    problems: list[str] = []
    dispatcher_types = set(dispatcher_map)
    enqueued = set(enqueue_types)
    if "Unknown" in dispatcher_types:
        problems.append("PendingMutationType.Unknown must not have a dispatcher")
    if "Unknown" in enqueued:
        problems.append("PendingMutationType.Unknown must never be enqueued (it only comes from fromWire)")
    for bad in sorted(dispatcher_types - enum_types):
        problems.append(f"dispatcher references PendingMutationType.{bad}, not a declared enum constant")
    for bad in sorted(enqueued - enum_types):
        problems.append(f"enqueue references PendingMutationType.{bad}, not a declared enum constant")
    return problems


def _check_registration(dispatcher_map: dict[str, str], registered_classes: set[str]) -> list[str]:
    """Every dispatcher class is registered; every registered class is a real dispatcher."""
    problems: list[str] = []
    for mutation_type, cls in sorted(dispatcher_map.items()):
        if cls not in registered_classes:
            problems.append(
                f"{cls} (PendingMutationType.{mutation_type}) is not registered in AppContainer.outboxDispatchers"
            )
    for cls in sorted(registered_classes - set(dispatcher_map.values())):
        problems.append(f"AppContainer registers {cls}, which is not an OutboxMutationDispatcher impl (renamed/removed?)")
    return problems


def _check_enqueue_has_dispatcher(
    real_enum: set[str],
    dispatcher_map: dict[str, str],
    registered_classes: set[str],
    enqueue_types: dict[str, set[str]],
) -> list[str]:
    """The core silent-bug check: an enqueued type with no registered dispatcher → FAILED rows."""
    problems: list[str] = []
    for mutation_type in sorted(set(enqueue_types) & real_enum):
        cls = dispatcher_map.get(mutation_type)
        where = ", ".join(sorted(enqueue_types.get(mutation_type, set())))
        if cls is None:
            problems.append(
                f"PendingMutationType.{mutation_type} is enqueued ({where}) but has no dispatcher - rows drain to FAILED"
            )
        elif cls not in registered_classes:
            problems.append(
                f"PendingMutationType.{mutation_type} is enqueued ({where}) but its dispatcher {cls} is not registered"
            )
    return problems


def _check_reachability(
    real_enum: set[str],
    dispatcher_map: dict[str, str],
    enqueue_types: dict[str, set[str]],
    allowlist_no_callsite: frozenset[str],
) -> list[str]:
    """A registered dispatcher whose type is never enqueued is dead wiring; keep the allowlist honest."""
    problems: list[str] = []
    dispatcher_types = set(dispatcher_map)
    enqueued = set(enqueue_types)
    for mutation_type in sorted(dispatcher_types & real_enum):
        if mutation_type not in enqueued and mutation_type not in allowlist_no_callsite:
            problems.append(
                f"PendingMutationType.{mutation_type} has a dispatcher but no enqueue call site (dead wiring); "
                f"add a call site or list it in DISPATCHER_WITHOUT_CALLSITE"
            )
    for stale in sorted(allowlist_no_callsite - dispatcher_types):
        problems.append(f"DISPATCHER_WITHOUT_CALLSITE lists {stale}, which has no dispatcher")
    for resolved in sorted(allowlist_no_callsite & enqueued):
        problems.append(f"DISPATCHER_WITHOUT_CALLSITE lists {resolved}, but it now has a call site — remove it")
    return problems


def evaluate(
    *,
    enum_types: set[str],
    dispatcher_map: dict[str, str],
    registered_classes: set[str],
    enqueue_types: dict[str, set[str]],
    allowlist_no_callsite: frozenset[str],
) -> list[str]:
    """Return human-readable 3-way-consistency problems; empty list == OK."""
    real_enum = enum_types - {"Unknown"}
    if "Unknown" not in enum_types or not real_enum:
        return ["PendingMutationType enum could not be parsed (no constants / no Unknown sentinel)"]

    return [
        *_check_unknown_and_constants(enum_types, dispatcher_map, enqueue_types),
        *_check_registration(dispatcher_map, registered_classes),
        *_check_enqueue_has_dispatcher(real_enum, dispatcher_map, registered_classes, enqueue_types),
        *_check_reachability(real_enum, dispatcher_map, enqueue_types, allowlist_no_callsite),
    ]


def _kt_files(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): _read(path) for path in root.rglob("*.kt")}


def main() -> int:
    files = _kt_files(ANDROID_SRC)
    enum_types = parse_enum_types(_read(TYPE_FILE))
    dispatcher_map = parse_dispatchers(files)
    registered_classes = parse_registered_classes(_read(APP_CONTAINER))
    enqueue_types = parse_enqueues(files, enum_types)

    problems = evaluate(
        enum_types=enum_types,
        dispatcher_map=dispatcher_map,
        registered_classes=registered_classes,
        enqueue_types=enqueue_types,
        allowlist_no_callsite=DISPATCHER_WITHOUT_CALLSITE,
    )

    if problems:
        print("FAIL: Android outbox enum <-> dispatcher <-> enqueue drift:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    real = enum_types - {"Unknown"}
    forward = sorted(real - set(dispatcher_map) - set(enqueue_types))
    print(
        f"PASS: outbox 3-way consistency holds - {len(real)} mutation types, "
        f"{len(dispatcher_map)} dispatchers (all registered + enqueued), "
        f"{len(enqueue_types)} enqueued types. "
        f"forward-declared (not yet wired): {len(forward)}"
        + (f" [{', '.join(forward)}]" if forward else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
