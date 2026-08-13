from __future__ import annotations

import ast
import re
from pathlib import Path

REGISTRY_MODULE = "app.database_model_registry"
OWNER_PRIMITIVES = {"DeclarativeBase", "MetaData", "declarative_base", "registry"}
LEGACY_BASE_IMPORT = re.compile(
    r"from\s+app\.database(?:\._core)?\s+import\s+"
    r"(?P<names>\([^)]*\)|[^\r\n]+)",
    re.MULTILINE,
)


def _record_sqlalchemy_import(
    node: ast.Import,
    module_paths: dict[str, tuple[str, ...]],
) -> None:
    for alias in node.names:
        imported_path = tuple(alias.name.split("."))
        if imported_path[:1] != ("sqlalchemy",):
            continue
        local_name = alias.asname or imported_path[0]
        module_paths[local_name] = imported_path if alias.asname else ("sqlalchemy",)


def _record_sqlalchemy_from_import(
    node: ast.ImportFrom,
    declarative_base_names: set[str],
    factory_names: set[str],
    module_paths: dict[str, tuple[str, ...]],
    sites: list[str],
) -> None:
    if node.module is None or node.module.split(".")[0] != "sqlalchemy":
        return
    for alias in node.names:
        local_name = alias.asname or alias.name
        if alias.name in {"orm", "schema", "sql"}:
            module_paths[local_name] = (*node.module.split("."), alias.name)
            continue
        if alias.name not in OWNER_PRIMITIVES:
            continue
        sites.append(f"primitive-import:{alias.name}")
        if alias.name == "DeclarativeBase":
            declarative_base_names.add(local_name)
        else:
            factory_names.add(local_name)


def _sqlalchemy_import_context(
    tree: ast.AST,
) -> tuple[set[str], set[str], dict[str, tuple[str, ...]], list[str]]:
    declarative_base_names: set[str] = set()
    factory_names: set[str] = set()
    module_paths: dict[str, tuple[str, ...]] = {}
    sites: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _record_sqlalchemy_import(node, module_paths)
        elif isinstance(node, ast.ImportFrom):
            _record_sqlalchemy_from_import(
                node,
                declarative_base_names,
                factory_names,
                module_paths,
                sites,
            )
    return declarative_base_names, factory_names, module_paths, sites


def _qualified_owner_primitive(
    node: ast.expr,
    module_paths: dict[str, tuple[str, ...]],
) -> str | None:
    attributes: list[str] = []
    cursor = node
    while isinstance(cursor, ast.Attribute):
        attributes.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name) or cursor.id not in module_paths:
        return None
    resolved = (*module_paths[cursor.id], *reversed(attributes))
    primitive = resolved[-1]
    if primitive not in OWNER_PRIMITIVES or resolved[:1] != ("sqlalchemy",):
        return None
    return primitive


def module_imports_base(path: Path, module: str = REGISTRY_MODULE) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == "Base" for alias in node.names)
        for node in ast.walk(tree)
    )


def legacy_base_import(text: str) -> str | None:
    return next(
        (
            match.group(0)
            for match in LEGACY_BASE_IMPORT.finditer(text)
            if re.search(r"\bBase\b", match.group("names"))
        ),
        None,
    )


def metadata_owner_sites(path: Path) -> list[str]:
    """Return every application reference capable of creating metadata authority."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declarative_names, factory_names, module_paths, sites = (
        _sqlalchemy_import_context(tree)
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and (
            primitive := _qualified_owner_primitive(node, module_paths)
        ) is not None:
            sites.append(f"qualified-reference:{primitive}")
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(base, ast.Name) and base.id in declarative_names)
            or _qualified_owner_primitive(base, module_paths) == "DeclarativeBase"
            for base in node.bases
        ):
            sites.append("declarative-subclass")
        if isinstance(node, ast.Call):
            called_name = node.func.id if isinstance(node.func, ast.Name) else None
            if called_name in factory_names:
                sites.append(f"factory:{called_name}")
            elif _qualified_owner_primitive(node.func, module_paths) in OWNER_PRIMITIVES - {
                "DeclarativeBase"
            }:
                primitive = _qualified_owner_primitive(node.func, module_paths)
                sites.append(f"qualified-factory:{primitive}")
    return sites


def declared_model_tables(model_root: Path) -> set[str]:
    tables: set[str] = set()
    for path in model_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in node.targets
            ):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                tables.add(node.value.value)
    return tables


def assert_unique_alembic_metadata_binding(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    alembic_context_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("alembic")
    ]
    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name.startswith("alembic") for alias in node.names)
        for node in ast.walk(tree)
    )
    assert len(alembic_context_imports) == 1
    assert alembic_context_imports[0].module == "alembic"
    assert [(alias.name, alias.asname) for alias in alembic_context_imports[0].names] == [
        ("context", None)
    ]
    target_stores = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
        and node.id == "target_metadata"
    ]
    assert len(target_stores) == 1

    bindings = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "target_metadata"
    ]
    assert len(bindings) == 1
    binding = bindings[0]
    assert isinstance(binding, ast.Attribute)
    assert binding.attr == "metadata"
    assert isinstance(binding.value, ast.Name)
    assert binding.value.id == "Base"

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    configure_references = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "configure"
    ]
    assert len(configure_references) == 3
    for reference in configure_references:
        assert isinstance(reference.value, ast.Name)
        assert reference.value.id == "context"
        parent = parents[reference]
        assert isinstance(parent, ast.Call) and parent.func is reference

    metadata_consumers = [parents[reference] for reference in configure_references]
    calls_with_metadata = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(keyword.arg == "target_metadata" for keyword in node.keywords)
    ]
    assert len(metadata_consumers) == 3
    assert set(calls_with_metadata) == set(metadata_consumers)
    for call in metadata_consumers:
        assert all(keyword.arg is not None for keyword in call.keywords)
        metadata_keywords = [
            keyword for keyword in call.keywords if keyword.arg == "target_metadata"
        ]
        assert len(metadata_keywords) == 1
        value = metadata_keywords[0].value
        assert isinstance(value, ast.Name) and value.id == "target_metadata"
