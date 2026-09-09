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


def _code_only(source: str) -> str:
    tokens = r'//[^\n]*|/\*[\s\S]*?\*/|"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    return re.sub(tokens, lambda match: re.sub(r"[^\n]", " ", match.group()), source)


def _arguments(source: str) -> list[str]:
    """Split explicit Kotlin arguments without splitting nested calls or generic types."""
    out, start, stack = [], 0, []
    closing = {")": "(", "]": "[", "}": "{", ">": "<"}
    for index, char in enumerate(source):
        if char in "([{<":
            stack.append(char)
        elif stack and closing.get(char) == stack[-1] and source[max(0, index - 1):index] != "-":
            stack.pop()
        elif char == "," and not stack:
            out.append(source[start:index].strip())
            start = index + 1
    out.append(source[start:].strip())
    return [argument for argument in out if argument]


def _registered_calls(source: str) -> list[tuple[str, list[str]]]:
    out = []
    for expression in _arguments(_outbox_dispatchers_block(_code_only(source))):
        match = re.fullmatch(r"(?:[\w.]+\.)?(\w+Dispatcher)\s*\((.*)\)", expression, re.DOTALL)
        if match:
            out.append((match[1], _arguments(match[2])))
    return out


def _constructor_type(cls: str, arguments: list[str], index: int) -> str:
    named = next((part.split("=", 1)[1].strip() for part in arguments if re.match(r"type\s*=", part)), None)
    value = named if named is not None else (arguments[index] if index < len(arguments) else "")
    match = re.fullmatch(r"PendingMutationType\.(\w+)", value)
    if match is None:
        raise ValueError(f"{cls} constructor type is not an explicit PendingMutationType constant")
    return match[1]


def _dispatcher_declarations(files: dict[str, str]) -> tuple[dict[str, str], dict[str, int]]:
    type_re = re.compile(r"override\s+val\s+type\b[^=\n]*=\s*PendingMutationType\.(\w+)")
    class_re = re.compile(r"\bclass\s+(\w+)\b[^{]*:\s*[^{]*\bOutboxMutationDispatcher\b", re.DOTALL)
    any_class_re = re.compile(r"\bclass\s+\w+\b")
    out: dict[str, str] = {}
    parameters: dict[str, int] = {}
    for _name, source in files.items():
        source = _code_only(source)
        if "OutboxMutationDispatcher" not in source:
            continue
        class_starts = [match.start() for match in any_class_re.finditer(source)]
        for class_match in class_re.finditer(source):
            end = next(
                (start for start in class_starts if start > class_match.start()),
                len(source),
            )
            header = class_match.group()
            params = _arguments(header[header.find("(") + 1:header.rfind(")")])
            parameter = next((index for index, part in enumerate(params)
                if re.match(r"override\s+val\s+type\s*:\s*PendingMutationType\b", part)), None)
            if parameter is not None:
                parameters[class_match[1]] = parameter
                continue
            type_match = type_re.search(source, class_match.end(), end)
            if type_match is not None:
                _add_dispatcher(out, type_match[1], class_match[1])
    return out, parameters


def parse_dispatchers(files: dict[str, str], app_container_source: str = "") -> dict[str, str]:
    """Resolve fixed implementations and explicit constructor types at each registration."""
    out, parameters = _dispatcher_declarations(files)
    registered = set()
    for cls, arguments in _registered_calls(app_container_source):
        mutation_type = (_constructor_type(cls, arguments, parameters[cls]) if cls in parameters
            else next((kind for kind, owner in out.items() if owner == cls), None))
        if mutation_type is None:
            continue
        if mutation_type in registered:
            raise ValueError(f"duplicate dispatcher registration for PendingMutationType.{mutation_type}")
        registered.add(mutation_type)
        if cls in parameters:
            _add_dispatcher(out, mutation_type, cls)
    for cls in parameters.keys() - set(out.values()):
        raise ValueError(f"{cls} constructor type has no explicit registration in AppContainer.outboxDispatchers")
    return out


def _add_dispatcher(out: dict[str, str], mutation_type: str, cls: str) -> None:
    if mutation_type in out:
        raise ValueError(f"duplicate dispatcher implementation for PendingMutationType.{mutation_type}")
    out[mutation_type] = cls


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
    return {cls for cls, _ in _registered_calls(app_container_source)}


def _typed_intent_types(source: str) -> set[str]:
    """Inspect explicit constructor types, including a factory's conditional choice.

    This is construction coverage; real owner/Room tests establish reachability.
    Metadata and payload arguments cannot stand in for the mutation's type.
    """
    types = set()
    for match in re.finditer(r"\bPendingMutationIntent\s*\(", source):
        depth = 1
        for index in range(match.end(), len(source)):
            depth += (source[index] == "(") - (source[index] == ")")
            if depth != 0:
                continue
            arguments = _arguments(source[match.end():index])
            named = next((part for part in arguments if re.match(r"type\s*=", part)), None)
            expression = named if named is not None else next(iter(arguments), "")
            types.update(re.findall(r"\bPendingMutationType\.(\w+)\b(?!\s*\()", expression))
            break
    return types


def parse_enqueues(files: dict[str, str], enum_types: set[str]) -> dict[str, set[str]]:
    """Map enqueued ``PendingMutationType`` -> the files that enqueue it.

    Count explicit fields, enqueue arguments and typed intent constructions.
    Keep invalid references so evaluation can reject them.
    """
    out: dict[str, set[str]] = {}
    pattern = re.compile(r"\btype\s*=\s*PendingMutationType\.(\w+)\b(?!\s*\()")
    positional = re.compile(r"\benqueue\s*\(\s*[^,]+,\s*PendingMutationType\.(\w+)\b(?!\s*\()")
    for name, source in files.items():
        source = _code_only(source)
        for line in source.splitlines():
            if "override val type" in line:
                continue
            for match in pattern.finditer(line):
                constant = match.group(1)
                out.setdefault(constant, set()).add(name)
        for match in positional.finditer(source):
            out.setdefault(match[1], set()).add(name)
        for constant in _typed_intent_types(source):
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
    container = _read(APP_CONTAINER)
    try:
        dispatcher_map = parse_dispatchers(files, container)
    except ValueError as exc:
        print(f"FAIL: Android outbox dispatcher wiring: {exc}")
        return 1
    registered_classes = parse_registered_classes(container)
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
