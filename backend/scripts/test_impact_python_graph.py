"""Static Python module and import evidence for test-impact selection."""

from __future__ import annotations

import ast
import importlib.util
import tokenize
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from pathlib import Path

SOURCE_PREFIXES = ("app/", "scripts/", "tests/")


class ImpactEvidenceError(RuntimeError):
    """Raised when source evidence cannot support a partial selection."""


def _module_name(path: Path, backend_root: Path) -> str | None:
    try:
        relative = path.relative_to(backend_root)
    except ValueError:
        return None
    if relative.suffix != ".py" or relative.parts[0] not in {"app", "scripts", "tests"}:
        return None
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _source_modules(backend_root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for prefix in SOURCE_PREFIXES:
        source_root = backend_root / prefix.rstrip("/")
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*.py"):
            module = _module_name(path, backend_root)
            if module:
                modules[module] = path
    return modules


def _module_aliases(known_modules: Mapping[str, Path]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for canonical in known_modules:
        aliases[canonical] = canonical
        root, separator, runtime_name = canonical.partition(".")
        if root not in {"scripts", "tests"} or not separator:
            continue
        previous = aliases.get(runtime_name)
        if previous is not None and previous != canonical:
            raise ImpactEvidenceError(
                f"ambiguous Python import root {runtime_name}: {previous}, {canonical}"
            )
        aliases[runtime_name] = canonical
    return aliases


def _resolve_module_name(
    name: str,
    *,
    known_modules: Mapping[str, Path],
    module_aliases: Mapping[str, str],
) -> str | None:
    if name in known_modules:
        return name
    return module_aliases.get(name)


def _resolve_module_reference(
    reference: str,
    *,
    known_modules: Mapping[str, Path],
    module_aliases: Mapping[str, str],
) -> str | None:
    target = _resolve_module_name(
        reference,
        known_modules=known_modules,
        module_aliases=module_aliases,
    )
    if target is not None or not reference.endswith(".py"):
        return target
    normalized = (
        reference.replace("\\", "/")
        .removeprefix("backend/")
        .removesuffix(".py")
        .replace("/", ".")
    )
    return _resolve_module_name(
        normalized,
        known_modules=known_modules,
        module_aliases=module_aliases,
    )


def read_python_source(path: Path) -> str:
    try:
        with tokenize.open(path) as stream:
            return stream.read()
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ImpactEvidenceError(f"cannot read Python source {path}: {exc}") from exc


def _import_base(
    node: ast.ImportFrom,
    *,
    importer: str,
    importer_path: Path,
) -> str | None:
    base = node.module or ""
    if not node.level:
        return base
    package = importer if importer_path.name == "__init__.py" else importer.rpartition(".")[0]
    try:
        return importlib.util.resolve_name("." * node.level + base, package)
    except (ImportError, ValueError):
        return None


def _package_exports(
    known_modules: Mapping[str, Path],
) -> dict[tuple[str, str], str]:
    exports: dict[tuple[str, str], str] = {}
    for package, path in known_modules.items():
        if path.name != "__init__.py":
            continue
        try:
            tree = ast.parse(read_python_source(path), filename=str(path))
        except SyntaxError as exc:
            raise ImpactEvidenceError(f"cannot parse {path}: {exc}") from exc
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            base = _import_base(node, importer=package, importer_path=path)
            if not base:
                continue
            for alias in node.names:
                child_module = f"{base}.{alias.name}"
                target = child_module if child_module in known_modules else base
                if alias.name != "*" and target in known_modules:
                    exports[(package, alias.asname or alias.name)] = target
    return exports


def _from_import_targets(
    node: ast.ImportFrom,
    *,
    importer: str,
    importer_path: Path,
    known_modules: Mapping[str, Path],
    module_aliases: Mapping[str, str],
    package_exports: Mapping[tuple[str, str], str],
) -> set[str]:
    base = _import_base(node, importer=importer, importer_path=importer_path)
    if base is None:
        return set()
    imported: set[str] = set()
    canonical_base = _resolve_module_name(
        base,
        known_modules=known_modules,
        module_aliases=module_aliases,
    )
    if canonical_base is not None:
        imported.add(canonical_base)
    for alias in node.names:
        if alias.name == "*":
            continue
        exported_target = package_exports.get((canonical_base or base, alias.name))
        child_names = (
            f"{base}.{alias.name}" if base else alias.name,
            f"{canonical_base}.{alias.name}" if canonical_base is not None else alias.name,
        )
        candidate = exported_target
        if candidate is None:
            for child_name in child_names:
                candidate = _resolve_module_name(
                    child_name,
                    known_modules=known_modules,
                    module_aliases=module_aliases,
                )
                if candidate is not None:
                    break
        if candidate is not None:
            imported.add(candidate)
    return imported


def _plain_import_targets(
    node: ast.Import,
    *,
    known_modules: Mapping[str, Path],
    module_aliases: Mapping[str, str],
) -> set[str]:
    imported: set[str] = set()
    for alias in node.names:
        target = _resolve_module_reference(
            alias.name,
            known_modules=known_modules,
            module_aliases=module_aliases,
        )
        if target is not None:
            imported.add(target)
    return imported


def _constant_module_target(
    node: ast.Constant,
    *,
    known_modules: Mapping[str, Path],
    module_aliases: Mapping[str, str],
) -> set[str]:
    if not isinstance(node.value, str):
        return set()
    target = _resolve_module_reference(
        node.value,
        known_modules=known_modules,
        module_aliases=module_aliases,
    )
    return {target} if target is not None else set()


def _resolve_imported_modules(
    tree: ast.AST,
    *,
    importer: str,
    importer_path: Path,
    known_modules: Mapping[str, Path],
    module_aliases: Mapping[str, str],
    package_exports: Mapping[tuple[str, str], str],
) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(
                _plain_import_targets(
                    node,
                    known_modules=known_modules,
                    module_aliases=module_aliases,
                )
            )
        elif isinstance(node, ast.ImportFrom):
            imported.update(
                _from_import_targets(
                    node,
                    importer=importer,
                    importer_path=importer_path,
                    known_modules=known_modules,
                    module_aliases=module_aliases,
                    package_exports=package_exports,
                )
            )
        elif isinstance(node, ast.Constant):
            imported.update(
                _constant_module_target(
                    node,
                    known_modules=known_modules,
                    module_aliases=module_aliases,
                )
            )
    return imported


def reverse_import_graph(
    backend_root: Path,
) -> tuple[dict[str, set[str]], dict[str, Path]]:
    modules = _source_modules(backend_root)
    module_aliases = _module_aliases(modules)
    package_exports = _package_exports(modules)
    reverse: dict[str, set[str]] = defaultdict(set)
    for importer, path in modules.items():
        try:
            tree = ast.parse(read_python_source(path), filename=str(path))
        except SyntaxError as exc:
            raise ImpactEvidenceError(f"cannot parse {path}: {exc}") from exc
        for imported in _resolve_imported_modules(
            tree,
            importer=importer,
            importer_path=path,
            known_modules=modules,
            module_aliases=module_aliases,
            package_exports=package_exports,
        ):
            if importer != "app.main" or not imported.startswith("app.routes."):
                reverse[imported].add(importer)
    return reverse, modules


def reverse_closure(
    seeds: Iterable[str],
    reverse: Mapping[str, set[str]],
) -> set[str]:
    affected = set(seeds)
    queue = deque(affected)
    while queue:
        affected_module = queue.popleft()
        for importer in reverse.get(affected_module, ()):
            if importer not in affected:
                affected.add(importer)
                queue.append(importer)
    return affected
