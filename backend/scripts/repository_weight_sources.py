"""Immutable source inventory and lexical line accounting for repository weight."""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath

from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Literal

LANGUAGES = {
    ".py": ("Python", "python"), ".spec": ("Python", "python"),
    ".kt": ("Kotlin", "kotlin"), ".kts": ("Kotlin", "kotlin"),
    ".java": ("Java", "java"), ".js": ("JavaScript", "javascript"),
    ".cjs": ("JavaScript", "javascript"), ".mjs": ("JavaScript", "javascript"),
    ".ts": ("TypeScript", "typescript"), ".css": ("CSS", "css"),
    ".html": ("HTML/Jinja", "html+jinja"), ".j2": ("HTML/Jinja", "html+jinja"),
    ".xml": ("XML", "xml"), ".sql": ("SQL", "sql"),
    ".ps1": ("PowerShell", "powershell"), ".psm1": ("PowerShell", "powershell"),
    ".iss": ("Inno Setup", "delphi"), ".sh": ("Shell", "bash"),
    ".bat": ("Batch", "batch"), ".cmd": ("Batch", "batch"),
    ".yml": ("YAML", "yaml"), ".yaml": ("YAML", "yaml"),
    ".toml": ("TOML", "toml"), ".mako": ("Mako", "mako"),
    ".ini": ("INI", "ini"), ".conf": ("Configuration", "ini"),
    ".properties": ("Java properties", "properties"), ".jsonc": ("JSONC", "json"),
}
DETEKT_BASELINES = {
    "android/app/detekt-baseline-grayDebug.xml": "production",
    "android/app/detekt-baseline-grayDebugUnitTest.xml": "test",
}
DETEKT_POLICY = "android/detekt.yml"
WINDOWS_RUNTIME_SCRIPTS = frozenset({
    "check_cloudflare_endpoint.ps1", "check_public_boundary.ps1", "check_selfuse_health.ps1",
    "check_service_status.ps1", "check_windows_task_status.ps1", "diagnose_ticketbox.ps1",
    "ensure_ticketbox_runtime.ps1", "install_windows_tasks.ps1", "maintenance_ticketbox.ps1",
    "restart_backend.ps1", "scheduled_public_boundary_check.ps1", "show_server_status.ps1",
    "start_backend.ps1", "start_backend_gui.ps1", "stop_backend.ps1", "uninstall_windows_tasks.ps1",
})
# Most-specific prefixes first; tests keep their module but have a separate role.
SOURCE_OWNERS = (
    ("backend/packaging/", "Windows lifecycle", "production"),
    ("distribution/windows/", "Windows lifecycle", "production"),
    ("backend/migrations/", "Migrations", "production"),
    ("backend/app/static/", "Web", "production"),
    ("backend/app/templates/", "Web", "production"),
    ("backend/app/", "Backend", "production"),
    ("backend/", "Backend", "tooling"),
    ("android/app/src/", "Android", "production"),
    ("android/", "Android", "tooling"),
    ("desktop/backend_manager/", "Desktop", "production"),
    ("desktop/", "Desktop", "tooling"),
    ("infra/cloudflare/public-surface-rate-limit/src/", "Public edge", "production"),
    ("infra/cloudflare/public-surface-rate-limit/", "Public edge", "tooling"),
)
COMMENT_DIRECTIVE = re.compile(
    r"\bnoqa\b(?:\s*:\s*[A-Z0-9, ]+)?|"
    r"\btype:\s*ignore(?:\[[^\]\n]+\])?|"
    r"\bpylint:\s*disable(?:-next)?(?:\s*=\s*[\w, -]+)?|"
    r"\b(?:eslint|stylelint)-disable(?:-next-line|-line)?(?:[ \t]+[\w/@., -]+)?|"
    r"@ts-(?:ignore|nocheck)\b|\bNOSONAR\b|#lizard\s+forgive[^\n]*",
)
CODE_DIRECTIVE = re.compile(
    r"@(?:(?:file|get|set|field):)?(?:kotlin\.)?Suppress(?:Lint|Warnings)?\s*\([^)]*\)|"
    r"(?:System\.Diagnostics\.CodeAnalysis\.)?SuppressMessage(?:Attribute)?\s*\([^)]*\)|"
    r"tools:ignore\s*=\s*[\"'][^\"']*[\"']|#pragma\s+warning\s+disable[^\n]*",
)


def git_bytes(repo: Path, *arguments: str, input_data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *arguments], cwd=repo, input=input_data, capture_output=True, check=True,
    ).stdout


def exact_commit(repo: Path, ref: str, label: str) -> str:
    try:
        value = git_bytes(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"cannot resolve exact {label}") from exc
    sha = value.decode("ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError(f"invalid exact {label}")
    return sha


def exclusion(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if not parts or parts[0] in {"docs", ".agents", ".claude", "tmp"}:
        return "documentation or local output"
    if set(parts) & {"vendor", "vendored", "node_modules", "generated", "__pycache__", ".gradle"}:
        return "vendor or generated"
    if path.startswith("android/") and ("build" in parts or "schemas" in parts):
        return "Android build output or generated schema"
    if path in DETEKT_BASELINES or "detekt-baseline" in PurePosixPath(path).name:
        return "analyzer debt metadata"
    if PurePosixPath(path).suffix.lower() not in LANGUAGES and path != "android/gradlew":
        return "non-source asset, data, documentation or lockfile"
    return None


def source_owner(path: str) -> tuple[str, str]:
    if path.startswith("scripts/") and PurePosixPath(path).name in WINDOWS_RUNTIME_SCRIPTS:
        return "Windows lifecycle", "production"
    module, role = next(((module, role) for prefix, module, role in SOURCE_OWNERS if path.startswith(prefix)),
                        ("Engineering", "tooling"))
    is_test = bool(set(PurePosixPath(path).parts) & {"tests", "test", "androidTest", "testFixtures"})
    if is_test or path.startswith(("android/macrobenchmark/", "android/baselineprofile/")):
        role = "test"
    return module, role


def read_snapshot(repo: Path, sha: str) -> tuple[dict[str, str], dict[str, int]]:
    entries: list[tuple[str, str]] = []
    excluded: Counter[str] = Counter()
    tree = git_bytes(repo, "ls-tree", "-r", "-z", "--full-tree", sha)
    for item in tree.split(b"\0"):
        if not item:
            continue
        header, raw_path = item.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        path = raw_path.decode("utf-8")
        reason = exclusion(path)
        metadata = path in DETEKT_BASELINES or path == DETEKT_POLICY
        if kind != "blob" or mode not in {"100644", "100755"}:
            excluded["non-regular Git entry"] += 1
        elif reason is None or metadata:
            entries.append((path, oid))
            if reason is not None:
                excluded[reason] += 1
        else:
            excluded[reason] += 1
    if not entries:
        return {}, dict(excluded)
    request = "".join(f"{oid}\n" for _, oid in entries).encode("ascii")
    stream = io.BytesIO(git_bytes(repo, "cat-file", "--batch", input_data=request))
    files: dict[str, str] = {}
    for path, oid in entries:
        actual, kind, raw_size = stream.readline().decode("ascii").split()
        if actual != oid or kind != "blob":
            raise ValueError(f"invalid Git blob metadata: {path}")
        content = stream.read(int(raw_size))
        if stream.read(1) != b"\n":
            raise ValueError(f"truncated Git blob: {path}")
        files[path] = content.decode("utf-8-sig").replace("\r\n", "\n")
    return files, dict(sorted(excluded.items()))


def _line_kind(token, value: str) -> str:
    if token in Comment or token in Literal.String.Doc:
        return "comment"
    return "code" if value.strip() else "blank"


def _suppression_records(path: str, text: str, tokens: list) -> list[dict]:
    records: list[dict] = []
    for offset, token, value in tokens:
        if token not in Comment:
            continue
        for match in COMMENT_DIRECTIVE.finditer(value):
            records.append({
                "path": path, "line": text.count("\n", 0, offset + match.start()) + 1,
                "signature": " ".join(match.group().split()),
            })
    position = 0
    for match in CODE_DIRECTIVE.finditer(text):
        while position + 1 < len(tokens) and tokens[position + 1][0] <= match.start():
            position += 1
        token = tokens[position][1]
        if token in Comment or token in Literal.String:
            continue
        records.append({
            "path": path, "line": text.count("\n", 0, match.start()) + 1,
            "signature": re.sub(r"\s+", "", match.group()),
        })
    return records


def measure_source(path: str, text: str) -> tuple[dict, list[dict]]:
    language, alias = LANGUAGES.get(PurePosixPath(path).suffix.lower(), ("Shell", "bash"))
    tokens = list(get_lexer_by_name(alias).get_tokens_unprocessed(text))
    lines = text.splitlines()
    kinds = [set() for _ in lines]
    line_index = 0
    for _offset, token, value in tokens:
        for part in value.splitlines(keepends=True):
            if line_index < len(kinds) and part.strip():
                kinds[line_index].add(_line_kind(token, part))
            line_index += part.count("\n")
    if language == "Inno Setup":
        for index, line in enumerate(lines):
            if line.lstrip().startswith(";"):
                kinds[index] = {"comment"}
    code = sum("code" in kind for kind in kinds)
    comment = sum(bool(kind) and "code" not in kind for kind in kinds)
    module, role = source_owner(path)
    record = {
        "path": path, "directory": str(PurePosixPath(path).parent),
        "module": module, "role": role, "language": language,
        "normalized_source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "loc": len(lines), "code": code, "comment": comment, "blank": len(lines) - code - comment,
    }
    return record, _suppression_records(path, text, tokens)
