"""One-shot migration: rewrite tests/test_*.py to use the identity fixture
instead of conftest module globals and helper functions.

Phases (per file, in order):

1. cf.X rewrites (more specific — done before HELPER_REWRITES to avoid
   `cf.app_headers()` getting partially rewritten into `cf.identity.app_headers`).
2. helper-call rewrites (`app_headers()` -> `identity.app_headers`, etc.).
3. cf.BACKEND_ROOT / cf.PNG_BYTES -> bare names + auto-add imports.
4. upload_png / upload_png_as_raw_body call-site arity adjustment
   (insert identity as the second positional arg; multi-arg calls get
   headers=/path= keyword-rewritten).
5. Rewrite `from conftest import ...` -> `tests._infra.{env,assets}`;
   drop helper-name and CURRENT_* imports.
6. Drop `from conftest import CURRENT_* ` inline imports.
7. Drop unreferenced `import conftest as cf`.
8. Add `identity` parameter to any top-level `def` (test_* or module-level
   helper like `_foo`) whose body references `identity.` and which does not
   already have an `identity` parameter.
9. Rewrite call sites of file-local helpers that now have `identity` in
   their signature, so callers pass it through.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


HELPER_REWRITES: list[tuple[str, str]] = [
    (r"(?<!\.)\bgray_upload_url_path\(\)", "identity.gray_upload_url_path"),
    (r"(?<!\.)\bgray_upload_headers\(\)", "identity.gray_upload_headers"),
    (r"(?<!\.)\bgray_app_headers\(\)", "identity.gray_app_headers"),
    (r"(?<!\.)\bupload_url_path\(\)", "identity.upload_url_path"),
    (r"(?<!\.)\bupload_headers\(\)", "identity.upload_headers"),
    (r"(?<!\.)\badmin_headers\(\)", "identity.admin_headers"),
    (r"(?<!\.)\bapp_headers\(\)", "identity.app_headers"),
]

CF_REWRITES: list[tuple[str, str]] = [
    (r"\bcf\.CURRENT_APP_TOKEN\b", "identity.app_token"),
    (r"\bcf\.CURRENT_ADMIN_TOKEN\b", "identity.admin_token"),
    (r"\bcf\.CURRENT_UPLOAD_KEY\b", "identity.upload_key"),
    (r"\bcf\.CURRENT_PAIRING_CODE\b", "identity.pairing_code"),
    (r"\bcf\.CURRENT_TENANT_APP_TOKEN\b", "identity.tenant_app_token"),
    (r"\bcf\.CURRENT_TENANT_UPLOAD_KEY\b", "identity.tenant_upload_key"),
    (r"\bcf\.gray_upload_url_path\(\)", "identity.gray_upload_url_path"),
    (r"\bcf\.gray_upload_headers\(\)", "identity.gray_upload_headers"),
    (r"\bcf\.gray_app_headers\(\)", "identity.gray_app_headers"),
    (r"\bcf\.upload_url_path\(\)", "identity.upload_url_path"),
    (r"\bcf\.upload_headers\(\)", "identity.upload_headers"),
    (r"\bcf\.admin_headers\(\)", "identity.admin_headers"),
    (r"\bcf\.app_headers\(\)", "identity.app_headers"),
    (r"\bcf\.BACKEND_ROOT\b", "BACKEND_ROOT"),
    (r"\bcf\.PNG_BYTES\b", "PNG_BYTES"),
]


HELPER_NAMES = {
    "app_headers", "admin_headers", "upload_headers",
    "gray_app_headers", "gray_upload_headers",
    "upload_url_path", "gray_upload_url_path",
}

ENV_NAMES = {
    "BACKEND_ROOT", "TEST_DB_PATH", "TEST_UPLOAD_DIR", "TEST_UPLOAD_RELATIVE",
    "TEST_APP_TOKEN", "TEST_ADMIN_TOKEN", "TEST_UPLOAD_TOKEN",
    "TEST_TENANT_APP_TOKEN", "TEST_TENANT_UPLOAD_TOKEN",
}

ASSET_NAMES = {"PNG_BYTES"}

CURRENT_NAMES = {
    "CURRENT_APP_TOKEN", "CURRENT_ADMIN_TOKEN", "CURRENT_UPLOAD_KEY",
    "CURRENT_PAIRING_CODE", "CURRENT_TENANT_APP_TOKEN", "CURRENT_TENANT_UPLOAD_KEY",
}

# Known cross-file helpers whose signature now is
# ``f(client, identity, *, headers=None, path=None)`` instead of the legacy
# positional headers/path form.
CROSS_FILE_HELPERS = {"upload_png", "upload_png_as_raw_body"}


def apply_textual_rewrites(text: str) -> str:
    for pattern, replacement in CF_REWRITES:
        text = re.sub(pattern, replacement, text)
    for pattern, replacement in HELPER_REWRITES:
        text = re.sub(pattern, replacement, text)
    return text


def ensure_bare_name_imports(text: str) -> str:
    """If text mentions bare BACKEND_ROOT / PNG_BYTES and they were never
    imported, add the import."""

    inserts: list[str] = []
    if re.search(r"(?<![A-Za-z_.])BACKEND_ROOT\b", text) and "BACKEND_ROOT" not in extract_imported_names(text):
        inserts.append("from tests._infra.env import BACKEND_ROOT")
    if re.search(r"(?<![A-Za-z_.])PNG_BYTES\b", text) and "PNG_BYTES" not in extract_imported_names(text):
        inserts.append("from tests._infra.assets import PNG_BYTES")
    if not inserts:
        return text
    return inject_imports(text, inserts)


def extract_imported_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(
        r"^(?:from [\w.]+ import\s+)(?:\(([^)]+)\)|([^\n]+))$",
        text,
        re.MULTILINE,
    ):
        body = match.group(1) or match.group(2) or ""
        for chunk in body.replace("\n", ",").split(","):
            name = chunk.strip().split(" as ")[0].strip()
            if name:
                names.add(name)
    return names


def inject_imports(text: str, new_imports: list[str]) -> str:
    """Insert imports after the last `from ...` or `import ...` block."""
    lines = text.splitlines(keepends=True)
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            last_import_idx = i
        elif stripped == "" and last_import_idx == i - 1:
            # blank line right after import — extend the block
            pass
    if last_import_idx == -1:
        # no imports yet (rare) — insert after module docstring if any
        insert_at = 0
        for i, line in enumerate(lines):
            if not line.strip().startswith(('"""', "'''", "#")) and line.strip():
                insert_at = i
                break
        for imp in reversed(new_imports):
            lines.insert(insert_at, imp + "\n")
        return "".join(lines)
    for imp in new_imports:
        lines.insert(last_import_idx + 1, imp + "\n")
        last_import_idx += 1
    return "".join(lines)


def rewrite_imports(text: str) -> str:
    pattern = re.compile(
        r"^from conftest import\s+(?:\(([^)]+)\)|([^\n]+))\s*$",
        re.MULTILINE,
    )

    def replace(match: re.Match[str]) -> str:
        body = match.group(1) or match.group(2) or ""
        raw_names = [n.strip() for n in body.replace("\n", " ").split(",")]
        names = {n for n in raw_names if n}
        env_imports = sorted(n for n in names if n in ENV_NAMES)
        asset_imports = sorted(n for n in names if n in ASSET_NAMES)
        leftover = names - set(env_imports) - set(asset_imports) - HELPER_NAMES - CURRENT_NAMES
        new_lines: list[str] = []
        if env_imports:
            new_lines.append(f"from tests._infra.env import {', '.join(env_imports)}")
        if asset_imports:
            new_lines.append(f"from tests._infra.assets import {', '.join(asset_imports)}")
        if leftover:
            new_lines.append(
                "from conftest import " + ", ".join(sorted(leftover))
                + "  # NOTE: unmigrated symbol"
            )
        return "\n".join(new_lines)

    return pattern.sub(replace, text)


def drop_import_conftest_as_cf(text: str) -> str:
    if not re.search(r"\bcf\.[A-Za-z_]", text):
        text = re.sub(r"^import conftest as cf.*\n", "", text, flags=re.MULTILINE)
    return text


def drop_inline_current_imports(text: str) -> str:
    text = re.sub(
        r"^\s*from conftest import\s+(?:CURRENT_[A-Z_]+\s*(?:,\s*CURRENT_[A-Z_]+\s*)*)(?:\s*#.*)?\n",
        "",
        text,
        flags=re.MULTILINE,
    )
    return text


def rewrite_cross_file_helper_calls(text: str) -> str:
    """Adjust upload_png / upload_png_as_raw_body call sites to the new
    ``(client, identity, *, headers=?, path=?)`` signature.

    Three arities handled (order matters — 3-arg first to avoid 1-arg
    regex eating multi-arg call shells):

    - ``f(a, b, c)`` -> ``f(a, identity, headers=b, path=c)``
    - ``f(a, b)``    -> ``f(a, identity, headers=b)``
    - ``f(a)``       -> ``f(a, identity)``

    Skipped when the call already passes a bare ``identity`` positional.
    """
    for name in CROSS_FILE_HELPERS:
        # 3-arg
        text = re.sub(
            rf"(?<!def )\b{name}\(\s*([^,()]+?)\s*,\s*([^,()]+(?:\([^()]*\))?)\s*,\s*([^,()]+(?:\([^()]*\))?)\s*\)",
            lambda m: rewrite_three(m, name),
            text,
        )
        # 2-arg
        text = re.sub(
            rf"(?<!def )\b{name}\(\s*([^,()]+?)\s*,\s*([^,()]+(?:\([^()]*\))?)\s*\)",
            lambda m: rewrite_two(m, name),
            text,
        )
        # 1-arg
        text = re.sub(
            rf"(?<!def )\b{name}\(\s*([^,()]+?)\s*\)",
            lambda m: rewrite_one(m, name),
            text,
        )
    return text


def _already_has_identity_arg(args_text: str) -> bool:
    return any(a.strip() == "identity" for a in args_text.split(","))


def rewrite_one(match: re.Match[str], name: str) -> str:
    arg = match.group(1).strip()
    if arg == "identity":
        return match.group(0)
    return f"{name}({arg}, identity=identity)"


def rewrite_two(match: re.Match[str], name: str) -> str:
    a, b = match.group(1).strip(), match.group(2).strip()
    if a == "identity":
        return match.group(0)
    return f"{name}({a}, identity=identity, headers={b})"


def rewrite_three(match: re.Match[str], name: str) -> str:
    a, b, c = match.group(1).strip(), match.group(2).strip(), match.group(3).strip()
    if a == "identity":
        return match.group(0)
    return f"{name}({a}, identity=identity, headers={b}, path={c})"


def add_identity_param_module_level(text: str, file_path: Path) -> tuple[str, set[str]]:
    """Add `identity` to any module-level def whose body references identity.

    Returns the rewritten text and the set of function names that now have
    `identity` as a parameter (used in the next phase to rewrite call sites).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        print(f"  ! AST parse failed for {file_path}: {e}", file=sys.stderr)
        return text, set()

    lines = text.splitlines(keepends=True)
    edits: list[tuple[int, int, str, str]] = []
    helpers_with_identity: set[str] = set()

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = (
            {arg.arg for arg in node.args.args}
            | {arg.arg for arg in node.args.kwonlyargs}
            | {arg.arg for arg in node.args.posonlyargs}
        )
        if node.args.vararg:
            params.add(node.args.vararg.arg)
        if node.args.kwarg:
            params.add(node.args.kwarg.arg)
        body_src = ast.get_source_segment(text, node) or ""
        body_uses_identity = "identity." in body_src or re.search(r"\bidentity\b", body_src) is not None
        if "identity" in params:
            helpers_with_identity.add(node.name)
            continue
        if not body_uses_identity:
            continue
        signature_text = "".join(lines[node.lineno - 1 : node.body[0].lineno])
        edits.append((node.lineno - 1, node.body[0].lineno, signature_text, node.name))

    edits.sort(key=lambda e: e[0], reverse=True)
    for start, end, signature_text, fn_name in edits:
        new_signature = inject_identity_param(signature_text, fn_name)
        if new_signature == signature_text:
            print(f"  ! could not inject identity into {fn_name} in {file_path}", file=sys.stderr)
            continue
        lines[start:end] = [new_signature]
        helpers_with_identity.add(fn_name)

    return "".join(lines), helpers_with_identity


def inject_identity_param(signature_text: str, fn_name: str) -> str:
    """Add ``identity`` as a keyword-only parameter to the function signature.

    Keyword-only is the only safe insertion: it doesn't shift existing
    positional bindings at any call site and it harmonises with the
    matching ``identity=identity`` call-site insertion done elsewhere.

    - If a ``*`` / ``*args`` marker already exists, insert just after it.
    - Otherwise append ``*, identity`` at the end of the parameter list.
    """
    open_idx = signature_text.find("(")
    if open_idx == -1:
        return signature_text
    depth = 0
    close_idx = -1
    for i in range(open_idx, len(signature_text)):
        c = signature_text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                close_idx = i
                break
    if close_idx == -1:
        return signature_text
    params_block = signature_text[open_idx + 1 : close_idx]
    if not params_block.strip():
        return signature_text[: open_idx + 1] + "*, identity" + signature_text[close_idx:]

    parts = split_params(params_block)
    star_idx = -1
    kwarg_idx = -1
    last_real_idx = -1
    for i, p in enumerate(parts):
        stripped = p.strip()
        if not stripped:
            continue
        last_real_idx = i
        if stripped.startswith("**"):
            if kwarg_idx == -1:
                kwarg_idx = i
        elif stripped.startswith("*"):
            if star_idx == -1:
                star_idx = i

    if star_idx >= 0:
        # Insert immediately after the `*` / `*args` marker (now keyword-only land).
        new_parts = parts[: star_idx + 1] + [" identity"] + parts[star_idx + 1 :]
    elif kwarg_idx >= 0:
        # No `*` marker but a `**kwargs` exists. Insert `*, identity` just
        # before the `**kwargs` block (kwarg must always be last).
        new_parts = parts[:kwarg_idx] + [" *", " identity"] + parts[kwarg_idx:]
    elif last_real_idx >= 0:
        new_parts = parts[: last_real_idx + 1] + [" *", " identity"] + parts[last_real_idx + 1 :]
    else:
        new_parts = ["*, identity"]
    new_block = ",".join(new_parts)
    return signature_text[: open_idx + 1] + new_block + signature_text[close_idx:]


def split_params(params_block: str) -> list[str]:
    """Split a parameter block by top-level commas (ignoring those inside
    nested brackets / parens / quoted strings)."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    last = 0
    for i, c in enumerate(params_block):
        if quote:
            if c == quote and params_block[i - 1] != "\\":
                quote = None
            continue
        if c in "\"'":
            quote = c
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(params_block[last:i])
            last = i + 1
    parts.append(params_block[last:])
    return parts


def has_default(param: str) -> bool:
    """Detect whether a (single) parameter chunk carries a default value."""
    depth = 0
    quote: str | None = None
    for i, c in enumerate(param):
        if quote:
            if c == quote and param[i - 1] != "\\":
                quote = None
            continue
        if c in "\"'":
            quote = c
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "=" and depth == 0:
            return True
    return False


def rewrite_local_helper_calls(text: str, helper_names: set[str]) -> str:
    """For each file-local helper that now has ``identity`` appended to its
    signature, splice ``identity=identity`` before the closing ``)`` of every
    call site. AST col_offset values are UTF-8 byte offsets, so this routine
    operates on bytes and decodes back at the end (otherwise calls past any
    multi-byte char on the same line land at the wrong char index).
    """
    target_names = helper_names - CROSS_FILE_HELPERS
    if not target_names:
        return text
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text

    data = text.encode("utf-8")
    line_starts = compute_line_starts_bytes(data)
    edits: list[tuple[int, bytes]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in target_names:
            continue
        if any(isinstance(a, ast.Name) and a.id == "identity" for a in node.args):
            continue
        if any(kw.arg == "identity" for kw in node.keywords):
            continue
        if node.end_lineno is None or node.end_col_offset is None:
            continue
        insert_offset = line_starts[node.end_lineno - 1] + node.end_col_offset - 1
        trailing = data[:insert_offset].rstrip()
        if not node.args and not node.keywords:
            edits.append((insert_offset, b"identity=identity"))
        elif trailing.endswith(b","):
            edits.append((insert_offset, b" identity=identity"))
        else:
            edits.append((insert_offset, b", identity=identity"))

    if not edits:
        return text
    edits.sort(key=lambda e: e[0], reverse=True)
    for offset, insertion in edits:
        data = data[:offset] + insertion + data[offset:]
    return data.decode("utf-8")


def compute_line_starts_bytes(data: bytes) -> list[int]:
    """Byte offsets of each 1-indexed line's first byte."""
    starts = [0]
    for i, b in enumerate(data):
        if b == 0x0A:  # '\n'
            starts.append(i + 1)
    return starts


def migrate_file(path: Path, *, write: bool) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    text = apply_textual_rewrites(text)
    text = rewrite_cross_file_helper_calls(text)
    text = rewrite_imports(text)
    text = drop_inline_current_imports(text)
    text = drop_import_conftest_as_cf(text)
    # Fixpoint: a helper's body may only reference `identity` *after* its
    # own callees have been rewritten to pass it, which then forces the
    # outer helper to grow an `identity` parameter, which forces its
    # callers to be rewritten too. Iterate until stable.
    for _ in range(8):
        previous = text
        text, helpers_with_identity = add_identity_param_module_level(text, path)
        text = rewrite_local_helper_calls(text, helpers_with_identity)
        if text == previous:
            break
    else:
        print(f"  ! fixpoint did not converge for {path}", file=sys.stderr)
    text = ensure_bare_name_imports(text)
    if text != original:
        if write:
            path.write_text(text, encoding="utf-8")
        return True
    return False


def main(argv: list[str]) -> int:
    write = "--write" in argv
    targets = sorted(Path("tests").glob("test_*.py"))
    targets.append(Path("tests/api_contract_helpers.py"))
    changed = 0
    for path in targets:
        if not path.exists():
            continue
        if migrate_file(path, write=write):
            print(f"  changed: {path}")
            changed += 1
    mode = "WRITE" if write else "DRY-RUN"
    print(f"\n[{mode}] {changed} files updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
