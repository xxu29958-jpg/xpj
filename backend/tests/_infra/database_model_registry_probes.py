from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests._infra.database_model_registry_analysis import REGISTRY_MODULE


def run_isolated_probe(
    backend_root: Path,
    probe: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe, str(backend_root), *arguments],
        cwd=backend_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


RUNTIME_DATABASE_FREE_IMPORT_PROBE = r'''
import builtins
import importlib
import sys
import dotenv
import sqlalchemy
import sqlalchemy.engine as sync_engine
import sqlalchemy.engine.create as sync_engine_create
import sqlalchemy.ext.asyncio as async_engine
import sqlalchemy.ext.asyncio.engine as async_engine_create

sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
engine_calls = []
dotenv_calls = []

def reject_engine(*args, **kwargs):
    engine_calls.append(args[0] if args else None)
    raise AssertionError("leaf import attempted to construct a runtime engine")

def reject_dotenv(*args, **kwargs):
    dotenv_calls.append(args[0] if args else None)
    raise AssertionError("leaf import attempted to read runtime dotenv state")

sqlalchemy.create_engine = reject_engine
sync_engine.create_engine = reject_engine
sync_engine_create.create_engine = reject_engine
async_engine.create_async_engine = reject_engine
async_engine_create.create_async_engine = reject_engine
dotenv.load_dotenv = reject_dotenv

def reject_runtime_database(name, globals=None, locals=None, fromlist=(), level=0):
    if (
        name == "app.config"
        or name == "app.database"
        or name.startswith("app.database.")
        or (
            name == "app"
            and any(item == "config" or item == "database" for item in fromlist)
        )
    ):
        raise AssertionError(f"runtime database dependency imported: {name}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = reject_runtime_database
for module_name in sys.argv[2:]:
    importlib.import_module(module_name)
assert engine_calls == []
assert dotenv_calls == []
assert "app.config" not in sys.modules
assert not any(
    name == "app.database" or name.startswith("app.database.")
    for name in sys.modules
)
'''


def assert_runtime_database_free_imports(
    backend_root: Path,
    *module_names: str,
) -> None:
    completed = run_isolated_probe(
        backend_root,
        RUNTIME_DATABASE_FREE_IMPORT_PROBE,
        *module_names,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


RUNTIME_METADATA_PROBE = r'''
import builtins
import os
import sys
import dotenv
import sqlalchemy
import sqlalchemy.engine as sync_engine
import sqlalchemy.engine.create as sync_engine_create
import sqlalchemy.ext.asyncio as async_engine
import sqlalchemy.ext.asyncio.engine as async_engine_create
from sqlalchemy import inspect

sys.path.insert(0, sys.argv[1])
mode = sys.argv[3]
os.environ["TICKETBOX_DATA_DIR"] = sys.argv[4]
engine_calls = []
dotenv_calls = []
config_calls = []
config_imports = []

if mode == "preloaded-config":
    import app.config as runtime_config

    def reject_settings(*args, **kwargs):
        config_calls.append("get_settings")
        raise AssertionError("model registration attempted to resolve runtime settings")

    runtime_config.get_settings = reject_settings
elif mode != "clean":
    raise AssertionError(f"unknown import-order mode: {mode}")

original_import = builtins.__import__

def reject_config_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "app.config" or (name == "app" and "config" in fromlist):
        config_imports.append((name, tuple(fromlist)))
        raise AssertionError("model registration attempted to import runtime config")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = reject_config_import

def reject_engine(*args, **kwargs):
    engine_calls.append(args[0] if args else None)
    raise AssertionError("model registration attempted to construct a runtime engine")

def reject_dotenv(*args, **kwargs):
    dotenv_calls.append(args[0] if args else None)
    raise AssertionError("model registration attempted to read runtime dotenv state")

for owner, names in (
    (sqlalchemy, ("create_engine", "engine_from_config", "create_pool_from_url")),
    (sync_engine, ("create_engine", "engine_from_config", "create_pool_from_url")),
    (sync_engine_create, ("create_engine", "engine_from_config", "create_pool_from_url")),
    (async_engine, ("create_async_engine", "async_engine_from_config", "create_async_pool_from_url")),
    (async_engine_create, ("create_async_engine", "async_engine_from_config", "create_async_pool_from_url")),
):
    for name in names:
        if hasattr(owner, name):
            setattr(owner, name, reject_engine)
dotenv.load_dotenv = reject_dotenv

import app.models
from app.database_model_registry import Base
from tests._infra.database_model_registry_snapshot import metadata_digest

expected_tables = set(sys.argv[2].split(","))
mapped_classes = []
for exported_name in app.models.__all__:
    candidate = getattr(app.models, exported_name)
    try:
        mapper = inspect(candidate)
    except sqlalchemy.exc.NoInspectionAvailable:
        continue
    mapped_classes.append(candidate)
    assert mapper.registry is Base.registry, exported_name
    assert candidate.metadata is Base.metadata, exported_name

assert mapped_classes
assert engine_calls == [], engine_calls
assert dotenv_calls == [], dotenv_calls
assert config_calls == [], config_calls
assert config_imports == [], config_imports
if mode == "clean":
    assert "app.config" not in sys.modules
assert "app.database" not in sys.modules
assert "app.database._core" not in sys.modules
assert set(Base.metadata.tables) == expected_tables
print(metadata_digest(Base.metadata))
'''


def runtime_metadata_probe() -> str:
    return RUNTIME_METADATA_PROBE


def _embedded_reset_python(path: Path) -> str:
    reset_script = path.read_text(encoding="utf-8-sig")
    return reset_script.split("$py = @'", 1)[1].split("'@", 1)[0]


def _import_index(tree: ast.Module, module: str, name: str) -> int:
    return next(
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == name for alias in node.names)
    )


def _assert_reset_drop_binding(tree: ast.Module) -> int:
    drop_calls = [
        (index, node.value)
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "drop_all"
    ]
    assert len(drop_calls) == 1
    drop_index, drop_call = drop_calls[0]
    receiver = drop_call.func.value
    assert isinstance(receiver, ast.Attribute) and receiver.attr == "metadata"
    assert isinstance(receiver.value, ast.Name) and receiver.value.id == "Base"
    assert drop_call.args == []
    assert len(drop_call.keywords) == 1
    keyword = drop_call.keywords[0]
    assert keyword.arg == "bind"
    assert isinstance(keyword.value, ast.Name) and keyword.value.id == "engine"
    return drop_index


REMOTE_RESET_PROBE = r'''
import sys
import types

events = []
app = types.ModuleType("app")
app.__path__ = []
app.models = types.ModuleType("app.models")
config = types.ModuleType("app.config")
database = types.ModuleType("app.database")
registry = types.ModuleType("app.database_model_registry")

config.get_settings = lambda: types.SimpleNamespace(
    database_url="postgresql+psycopg://user:secret@remote.invalid/ticketbox"
)
database.engine = object()
database.init_db = lambda: events.append("init_db")
registry.Base = types.SimpleNamespace(
    metadata=types.SimpleNamespace(
        drop_all=lambda **kwargs: events.append(("drop_all", kwargs))
    )
)

sys.modules.update({
    "app": app,
    "app.models": app.models,
    "app.config": config,
    "app.database": database,
    "app.database_model_registry": registry,
})

try:
    exec(compile(sys.argv[1], "reset_dev_db.ps1:$py", "exec"), {})
except SystemExit as exc:
    assert "refusing reset" in str(exc), exc
else:
    raise AssertionError("remote reset did not fail closed")
assert events == [], events
'''


def _assert_remote_reset_refusal(embedded_python: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", REMOTE_RESET_PROBE, embedded_python],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def assert_reset_script_binding(path: Path) -> None:
    embedded_python = _embedded_reset_python(path)
    tree = ast.parse(embedded_python, filename=f"{path.name}:$py")
    drop_index = _assert_reset_drop_binding(tree)
    assert _import_index(tree, "app", "models") < drop_index
    assert _import_index(tree, REGISTRY_MODULE, "Base") < drop_index
    assert _import_index(tree, "app.database", "engine") < drop_index
    _assert_remote_reset_refusal(embedded_python)
