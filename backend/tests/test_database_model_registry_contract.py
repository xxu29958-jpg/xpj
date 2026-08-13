from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table

import app.tenant_contract as tenant_contract
from tests._infra.database_model_registry_analysis import (
    assert_unique_alembic_metadata_binding,
    declared_model_tables,
    legacy_base_import,
    metadata_owner_sites,
    module_imports_base,
)
from tests._infra.database_model_registry_probes import (
    assert_reset_script_binding,
    run_isolated_probe,
    runtime_metadata_probe,
)
from tests._infra.database_model_registry_snapshot import metadata_digest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
MODEL_ROOT = APP_ROOT / "models"
EXPECTED_TENANT_CONTRACT_ASSIGNMENTS = {
    "DEFAULT_TENANT_ID": "owner",
    "DEFAULT_TENANT_NAME": "我的小票夹",
}
MAINTAINED_SOURCE_SUFFIXES = {".iss", ".ps1", ".py", ".sh", ".spec"}


def test_model_registration_does_not_initialize_runtime_database() -> None:
    expected_tables = declared_model_tables(MODEL_ROOT)
    assert expected_tables

    metadata_digests = set()
    for import_order, poison_root in (
        ("clean", r"C:\poison\clean-metadata"),
        ("preloaded-config", r"D:\poison\preloaded-metadata"),
    ):
        completed = run_isolated_probe(
            BACKEND_ROOT,
            runtime_metadata_probe(),
            ",".join(sorted(expected_tables)),
            import_order,
            poison_root,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        metadata_digests.add(completed.stdout.strip())

    assert len(metadata_digests) == 1


def test_declarative_base_has_one_owner_and_no_runtime_reexport() -> None:
    owners: list[tuple[Path, str]] = []
    for path in APP_ROOT.rglob("*.py"):
        owners.extend(
            (path.relative_to(APP_ROOT), site) for site in metadata_owner_sites(path)
        )

    assert owners == [
        (Path("database_model_registry.py"), "primitive-import:DeclarativeBase"),
        (Path("database_model_registry.py"), "declarative-subclass"),
    ]

    for path in (APP_ROOT / "database" / "__init__.py", APP_ROOT / "database" / "_core.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == "Base" for alias in node.names)
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "Base"
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
            )
            for node in ast.walk(tree)
        )

    probe = r'''
import sys
sys.path.insert(0, sys.argv[1])
import app.database
import app.database._core as core
for module in (app.database, core):
    assert "Base" not in module.__dict__
    assert "Base" not in getattr(module, "__all__", ())
    try:
        getattr(module, "Base")
    except AttributeError:
        pass
    else:
        raise AssertionError(f"{module.__name__} dynamically re-exported Base")
'''
    completed = run_isolated_probe(BACKEND_ROOT, probe)
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_every_production_metadata_consumer_uses_the_registry_owner() -> None:
    model_consumers = []
    for path in sorted(MODEL_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.ClassDef)
            and any(isinstance(base, ast.Name) and base.id == "Base" for base in node.bases)
            for node in ast.walk(tree)
        ):
            model_consumers.append(path)

    assert model_consumers
    assert all(module_imports_base(path) for path in model_consumers)

    migration_env = BACKEND_ROOT / "migrations" / "env.py"
    assert module_imports_base(migration_env)
    assert_unique_alembic_metadata_binding(migration_env)
    assert module_imports_base(BACKEND_ROOT / "scripts" / "_audit_mutate_token_coverage.py")
    assert_reset_script_binding(BACKEND_ROOT / "scripts" / "reset_dev_db.ps1")

    tenant_contract_path = APP_ROOT / "tenant_contract.py"
    tenant_contract_tree = ast.parse(
        tenant_contract_path.read_text(encoding="utf-8"),
        filename=str(tenant_contract_path),
    )
    imports = [
        node
        for node in tenant_contract_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all(
        isinstance(node, ast.ImportFrom) and node.module == "__future__"
        or isinstance(node, ast.Import) and [alias.name for alias in node.names] == ["re"]
        for node in imports
    )
    assignments = {
        target.id: node.value.value
        for node in tenant_contract_tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance((target := node.targets[0]), ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert assignments == EXPECTED_TENANT_CONTRACT_ASSIGNMENTS
    assert assignments["DEFAULT_TENANT_ID"] == tenant_contract.DEFAULT_TENANT_ID
    assert assignments["DEFAULT_TENANT_NAME"] == tenant_contract.DEFAULT_TENANT_NAME

    forbidden_modules = {"app.database", "app.database._core"}
    for path in [*APP_ROOT.rglob("*.py"), migration_env]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(
            isinstance(node, ast.ImportFrom)
            and node.module in forbidden_modules
            and any(alias.name == "Base" for alias in node.names)
            for node in ast.walk(tree)
        ), path

    legacy_imports = []
    maintained_roots = (
        APP_ROOT,
        BACKEND_ROOT / "migrations",
        BACKEND_ROOT / "packaging",
        BACKEND_ROOT / "scripts",
    )
    for root in maintained_roots:
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.lower() not in MAINTAINED_SOURCE_SUFFIXES
                or "tests" in path.parts
                or "vendor" in path.parts
            ):
                continue
            legacy_import = legacy_base_import(path.read_text(encoding="utf-8"))
            if legacy_import is not None:
                legacy_imports.append((path.relative_to(BACKEND_ROOT), legacy_import))

    assert legacy_imports == []


def test_contract_oracles_reject_ambient_builtin_and_local_alembic_alias(
    tmp_path: Path,
) -> None:
    def ambient_default() -> str:
        return open("ambient.txt", encoding="utf-8").read()

    ambient_default.__module__ = "app.models.synthetic"
    metadata = MetaData()
    Table(
        "synthetic",
        metadata,
        Column("value", String(), default=ambient_default),
    )
    with pytest.raises(AssertionError, match="unapproved built-in"):
        metadata_digest(metadata)

    migration_env = BACKEND_ROOT / "migrations" / "env.py"
    mutated_env = tmp_path / "env.py"
    mutated_env.write_text(
        migration_env.read_text(encoding="utf-8")
        + "\n\ndef hidden_consumer(kwargs):\n"
        + "    from alembic.context import configure as cfg\n"
        + "    cfg(**kwargs)\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        assert_unique_alembic_metadata_binding(mutated_env)
