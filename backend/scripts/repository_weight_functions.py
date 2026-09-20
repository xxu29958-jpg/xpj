"""Function-level navigation with explicitly named, language-appropriate metrics."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from collections import Counter
from contextlib import redirect_stderr
from html.parser import HTMLParser
from pathlib import Path

import lizard
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Keyword, Literal, Name

LIZARD_SUFFIXES = {"Python": ".py", "Kotlin": ".kt", "Java": ".java", "JavaScript": ".js", "TypeScript": ".ts"}
_FUNCTION_CONTEXT = "lizard-html-inno-powershell-functions-v1"


def _comments_without_exemptions(tokens, reader):
    """Source inventory owns exclusions; comments cannot silently hide measured code."""
    for token in tokens:
        comment = reader.get_comment_from_token(token)
        if comment is None:
            yield token
        else:
            yield from ("\n" for _ in range(comment.count("\n")))


class InlineScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.active = False
        self.scripts: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "script":
            attributes = dict(attrs)
            self.active = not attributes.get("src") and attributes.get("type", "") in {
                "", "module", "text/javascript", "application/javascript",
            }

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.active = False

    def handle_data(self, data: str) -> None:
        if self.active:
            self.scripts.append((self.getpos()[0] - 1, data))


def _lizard_functions(record: dict, text: str, language: str, offset: int = 0) -> list[dict]:
    if language == "Kotlin":
        # Annotation use-site targets are not property accessors. Lizard otherwise
        # opens a phantom `get` function at @get:Rule and consumes the class.
        # Keep every newline; actual get()/set() accessors remain measured.
        text = re.sub(r"@(get|set|field|property|receiver|param|setparam|delegate|file):", "@", text)
    processors = [lizard.preprocessing, _comments_without_exemptions, lizard.line_counter,
                  lizard.token_counter, lizard.condition_counter]
    diagnostics = io.StringIO()
    with redirect_stderr(diagnostics):
        info = lizard.FileAnalyzer(processors).analyze_source_code("source" + LIZARD_SUFFIXES[language], text)
    if diagnostics.getvalue():
        raise ValueError(f"incomplete function analysis: {record['path']}")
    return [{
        "path": record["path"], "module": record["module"], "role": record["role"], "language": language,
        "name": function.name, "line": function.start_line + offset, "end_line": function.end_line + offset,
        "length": function.end_line - function.start_line + 1, "parameters": function.parameter_count,
        "metric": "lizard_ccn", "complexity": function.cyclomatic_complexity,
    } for function in info.function_list]


def _inno_routine(record: dict, text: str, segment: list) -> dict | None:
    names = [value for _, kind, value in segment if kind in Name.Function]
    keywords = [value.lower() for _, kind, value in segment if kind in Keyword]
    if not names or "begin" not in keywords or {"external", "forward"}.intersection(keywords):
        return None
    line = text.count("\n", 0, segment[0][0]) + 1
    end_line = text.count("\n", 0, segment[-1][0]) + 1
    return {
        "path": record["path"], "module": record["module"], "role": record["role"], "language": "Inno Setup",
        "name": names[0], "line": line, "end_line": end_line, "length": end_line - line + 1,
        "parameters": None, "metric": "inno_decision_tokens",
        "complexity": sum(value in {"if", "for", "while", "repeat", "case", "except", "and", "or"} for value in keywords),
    }


def _inno_functions(record: dict, text: str) -> list[dict]:
    tokens = [(offset, kind, value) for offset, kind, value in get_lexer_by_name("delphi").get_tokens_unprocessed(text)
              if value.strip() and kind not in Comment and kind not in Literal.String]
    starts = [index for index, (_, kind, value) in enumerate(tokens)
              if kind in Keyword and value.lower() in {"function", "procedure"}]
    functions: list[dict] = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else len(tokens)
        if routine := _inno_routine(record, text, tokens[start:stop]):
            functions.append(routine)
    return functions


def _powershell_functions(records: list[dict], files: dict[str, str]) -> tuple[list[dict], str | None]:
    scripts = {row["path"]: row for row in records if row["language"] == "PowerShell"}
    if not scripts:
        return [], None
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        raise ValueError("PowerShell parser is required to measure these source files")
    result = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(Path(__file__).with_name("repository_weight_powershell.ps1"))],
        input=json.dumps([{"path": path, "source": files[path]} for path in scripts]),
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    if result.returncode != 0:
        raise ValueError("PowerShell source analysis did not complete (measured source was not executed)")
    measured = json.loads(result.stdout)
    functions = measured["functions"]
    for function in functions:
        record = scripts[function["path"]]
        function.update(module=record["module"], role=record["role"], language="PowerShell")
    return functions, measured["version"]


def _functions_for_record(record: dict, text: str) -> list[dict]:
    language = record["language"]
    if language in LIZARD_SUFFIXES:
        return _lizard_functions(record, text, language)
    if language == "HTML/Jinja":
        parser = InlineScripts()
        parser.feed(text)
        functions: list[dict] = []
        for offset, script in parser.scripts:
            functions.extend(_lizard_functions(record, script, "JavaScript", offset))
        return functions
    if language == "Inno Setup":
        return _inno_functions(record, text)
    return []


def measure_functions(
    files: dict[str, str],
    records: list[dict],
    *,
    identities: dict[str, tuple] | None = None,
    reuse=None,
) -> tuple[list[dict], dict[str, int], str | None]:
    functions: list[dict] = []
    powershell_records = [record for record in records if record["language"] == "PowerShell"]
    powershell_misses: list[dict] = []
    powershell_by_path: dict[str, list[dict]] = {}
    for record in powershell_records:
        path = record["path"]
        key = (*identities[path], _FUNCTION_CONTEXT) if identities is not None else None
        cached = reuse.load("functions", key) if reuse is not None and key is not None else None
        if cached is None:
            powershell_misses.append(record)
        else:
            powershell_by_path[path] = cached
    measured_powershell, measured_version = _powershell_functions(powershell_misses, files)
    measured_by_path = {record["path"]: [] for record in powershell_misses}
    for function in measured_powershell:
        measured_by_path[function["path"]].append(function)
    for record in powershell_misses:
        path = record["path"]
        powershell_by_path[path] = measured_by_path[path]
        if reuse is not None and identities is not None:
            reuse.store("functions", (*identities[path], _FUNCTION_CONTEXT), measured_by_path[path])
    if measured_version is not None and reuse is not None and reuse.enabled:
        reuse.powershell_parser = measured_version
    powershell_version = measured_version
    if powershell_records and powershell_version is None and reuse is not None:
        powershell_version = reuse.powershell_parser
    for record in powershell_records:
        functions.extend(powershell_by_path[record["path"]])

    analyzed_languages = set(LIZARD_SUFFIXES) | {"HTML/Jinja", "Inno Setup"}
    for record in records:
        if record["language"] not in analyzed_languages:
            continue
        path = record["path"]
        key = (*identities[path], _FUNCTION_CONTEXT) if identities is not None else None
        cached = reuse.load("functions", key) if reuse is not None and key is not None else None
        if cached is None:
            cached = _functions_for_record(record, files[path])
            if reuse is not None and key is not None:
                reuse.store("functions", key, cached)
        functions.extend(cached)
    debt: Counter[str] = Counter()
    for function in functions:
        key = f"{function['language']}:{function['module']}:{function['role']}"
        excess = max(0, function["complexity"] - 15)
        debt[f"function_complexity:{key}"] += int(excess > 0)
        debt[f"function_complexity_excess:{key}"] += excess
        if function["name"] != "<script>":
            debt[f"long_functions:{key}"] += int(function["length"] > 80)
    return sorted(functions, key=lambda row: (row["path"], row["line"], row["name"])), dict(debt), powershell_version
