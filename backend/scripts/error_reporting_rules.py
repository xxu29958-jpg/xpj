"""Bounded, read-only reporting-boundary discovery. No business-module imports."""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter

from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Literal

REPORTERS = {"app.error_reporting.report_error", "app.error_reporting.retain_handled_error"}
EXECUTORS = {"asyncio.create_task", "asyncio.ensure_future", "threading.Thread",
    "concurrent.futures.ThreadPoolExecutor", "concurrent.futures.ProcessPoolExecutor"}
CONFIGURATORS = {"logging.basicConfig", "logging.config.dictConfig", "logging.config.fileConfig"}
BROAD = {"Exception", "BaseException", "builtins.Exception", "builtins.BaseException", "sqlalchemy.exc.SQLAlchemyError"}


def syntax_id(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def name_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return name_of(node.value) + "." + node.attr
    return ""


def aliases_for(tree: ast.AST) -> dict[str, str]:
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update((part.asname or part.name.split(".")[0], part.name if part.asname else part.name.split(".")[0])
                for part in node.names)
        elif isinstance(node, ast.ImportFrom):
            aliases.update((part.asname or part.name, f"{node.module}.{part.name}") for part in node.names)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            called = resolve(node.value.func, aliases)
            if called in EXECUTORS or called == "logging.getLogger":
                aliases[name_of(target)] = called
    return aliases


def resolve(node: ast.AST, aliases: dict[str, str]) -> str:
    name = name_of(node)
    for prefix in sorted(aliases, key=len, reverse=True):
        if name == prefix or name.startswith(prefix + "."):
            return aliases[prefix] + name[len(prefix):]
    return name


def calls(node: ast.AST, aliases: dict[str, str]) -> set[str]:
    return {resolve(child.func, aliases) for child in ast.walk(node) if isinstance(child, ast.Call)}


def function_nodes(tree: ast.AST, prefix: str = "") -> dict[str, ast.AST]:
    result = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = prefix + node.name
            if not isinstance(node, ast.ClassDef):
                result[symbol] = node
            result.update(function_nodes(node, symbol + "."))
    return result


def handled(statements: list[ast.stmt], aliases: dict[str, str]) -> bool:
    """Only calibrated straight-line reporting/reraise, or both if arms, can inherit."""
    for statement in statements:
        if isinstance(statement, ast.Raise):
            return True
        if isinstance(statement, (ast.Return, ast.Break, ast.Continue)):
            return False
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            name = resolve(statement.value.func, aliases)
            if name in REPORTERS or name == "logging.getLogger.exception":
                return True
        if isinstance(statement, ast.If) and handled(statement.body, aliases) and handled(statement.orelse, aliases):
            return True
    return False


def _boundary(node: ast.AST, aliases: dict[str, str]) -> tuple[str, str] | None:
    if isinstance(node, ast.Dict):
        keys = {key.value for key in node.keys if isinstance(key, ast.Constant)}
        if {"handlers", "formatters"} <= keys:
            return "logging-output", "the configured root/child outputs and final sanitized formatter"
    if isinstance(node, ast.ExceptHandler):
        kinds = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        broad = node.type is None or any(kind is not None and resolve(kind, aliases) in BROAD for kind in kinds)
        if broad and not handled(node.body, aliases):
            return "terminal-catch", "common HTTP/task reporting or an explicit local terminal owner"
    if isinstance(node, ast.Call):
        name = resolve(node.func, aliases)
        if name in EXECUTORS or any(name == executor + ".submit" for executor in EXECUTORS):
            return "independent-execution", "observe the independent worker, including errors outside its handler"
        if name in CONFIGURATORS or name.startswith("logging.") and name.endswith("Handler"):
            return "logging-output", "existing final sanitized file/console output"
        if name.endswith((".addHandler", ".removeHandler", ".setFormatter")):
            return "logging-output", "existing final sanitized file/console output"
        if name == "contextlib.suppress" and any(resolve(arg, aliases) in BROAD for arg in node.args):
            return "terminal-suppress", "an explicit expected/sink failure owner"
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(name_of(target).endswith((".propagate", ".handlers", ".disabled")) for target in targets):
            return "logging-output", "existing final sanitized file/console output"
    return None


def python_boundaries(text: str) -> list[dict]:
    tree = ast.parse(text)
    aliases = aliases_for(tree)
    functions = function_nodes(tree)
    findings = []
    for node in ast.walk(tree):
        match = _boundary(node, aliases)
        if match is None:
            continue
        owners = [(symbol, function) for symbol, function in functions.items()
            if function.lineno <= node.lineno <= function.end_lineno]
        symbol, function = min(owners, key=lambda item: item[1].end_lineno - item[1].lineno) if owners else ("<module>", tree)
        findings.append({"rule": match[0], "symbol": symbol, "line": node.lineno, "owner": match[1],
            "boundary_sha256": syntax_id(function if isinstance(node, ast.Dict) else node), "symbol_sha256": syntax_id(function)})
    return findings


def kotlin_code(text: str) -> str:
    """Lexical candidates only; strings/comments are not execution evidence."""
    return "".join("".join("\n" if ch == "\n" else " " for ch in value)
        if token in Comment or token in Literal.String else value
        for _offset, token, value in get_lexer_by_name("kotlin").get_tokens_unprocessed(text))


def kotlin_boundaries(text: str) -> list[dict]:
    code = kotlin_code(text)
    findings = []
    log_names = {"Log"} | set(re.findall(r"import\s+android\.util\.Log\s+as\s+(\w+)", code))
    broad_names = {"Exception", "Throwable"} | set(re.findall(
        r"import\s+(?:kotlin|java\.lang)\.(?:Exception|Throwable)\s+as\s+(\w+)", code))
    pattern = re.compile(r"\bcatch\s*\(\s*\w+\s*:\s*(?:" + "|".join(sorted(broad_names)) +
        r")\b|\b(?:" + "|".join(sorted(log_names)) + r")\s*\.\s*[ew]\s*\(")
    for match in pattern.finditer(code):
        preceding = list(re.finditer(r"\bfun\s+(?:<[^>]+>\s*)?(\w+)\s*\(", code[:match.start()]))
        symbol = preceding[-1].group(1) if preceding else "<module>"
        # Preserve the entire function text for exact reviewed exceptions, not only the catch count.
        start = preceding[-1].start() if preceding else 0
        opening = code.find("{", start)
        depth, end = 0, len(code)
        for offset in range(opening, len(code)):
            depth += (code[offset] == "{") - (code[offset] == "}")
            if depth == 0:
                end = offset + 1
                break
        digest = hashlib.sha256(text[start:end].encode()).hexdigest()
        findings.append({"rule": "android-terminal-output", "symbol": symbol,
            "line": code[:match.start()].count("\n") + 1, "owner": "NetworkErrorHandler / sanitized Logcat boundary",
            "boundary_sha256": digest, "symbol_sha256": digest})
    return findings


def changed_boundaries(before: str, after: str, *, kotlin: bool = False) -> list[dict]:
    discover = kotlin_boundaries if kotlin else python_boundaries
    previous = Counter((item["rule"], item["symbol"], item["boundary_sha256"]) for item in discover(before))
    changed = []
    for item in discover(after):
        key = (item["rule"], item["symbol"], item["boundary_sha256"])
        if previous[key]:
            previous[key] -= 1
        else:
            changed.append(item)
    return changed
