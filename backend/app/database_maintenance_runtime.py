"""Physical source loader and process guards for the frozen database helper."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

GENERATION_PROGRAM_FILENAME = "DATABASE_GENERATION_PROGRAM.json"


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_generation_program(path: Path) -> Path:
    if path != Path(GENERATION_PROGRAM_FILENAME):
        raise RuntimeError("generation program must be the payload-root artifact")
    return (_bundle_dir() / path).resolve(strict=True)


def _maintenance_source_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not isinstance(bundle_root, str) or not bundle_root:
            raise RuntimeError("frozen database maintenance source root is unavailable")
        backend_root = Path(bundle_root)
    else:
        backend_root = Path(__file__).resolve().parents[1]
    return backend_root / "app" / "database" / filename


@contextmanager
def _temporary_database_package(source_path: Path) -> Iterator[None]:
    """Expose one physical helper package without importing the runtime facade."""

    database_module_name = "app.database"
    if database_module_name in sys.modules:
        raise RuntimeError("standalone database maintenance process already loaded app.database")
    app_package = importlib.import_module("app")
    if hasattr(app_package, "database"):
        raise RuntimeError("standalone database maintenance process has an unexpected database facade")

    package = ModuleType(database_module_name)
    package.__package__ = database_module_name
    package.__path__ = [str(source_path.parent)]
    package.__spec__ = importlib.machinery.ModuleSpec(
        database_module_name,
        loader=None,
        is_package=True,
    )
    sys.modules[database_module_name] = package
    app_package.database = package
    try:
        yield
        if sys.modules.get(database_module_name) is not package:
            raise RuntimeError("standalone database maintenance package identity changed")
    finally:
        for name in tuple(sys.modules):
            if name == database_module_name or name.startswith(f"{database_module_name}."):
                sys.modules.pop(name, None)
        if hasattr(app_package, "database"):
            delattr(app_package, "database")


def load_standalone_database_module(
    *,
    module_name: str,
    filename: str,
    database_package_seam: bool = False,
) -> ModuleType:
    """Load one attested action without executing ``app.database.__init__``."""

    source_path = _maintenance_source_path(filename).resolve()
    if not source_path.is_file():
        raise RuntimeError("standalone database maintenance source is unavailable")
    backend_root_text = str(source_path.parents[2])
    if backend_root_text not in sys.path:
        sys.path.insert(0, backend_root_text)
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        if Path(str(existing.__file__)).resolve() != source_path:
            raise RuntimeError("standalone database maintenance module identity changed")
        return existing
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("standalone database maintenance module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        if database_package_seam:
            with _temporary_database_package(source_path):
                spec.loader.exec_module(module)
        else:
            spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def assert_maintenance_libpq_environment(pgpassfile: Path) -> None:
    """Fail closed unless libpq sees only the attested one-shot passfile."""

    pg_entries = [(name, value) for name, value in os.environ.items() if name.upper().startswith("PG")]
    if len(pg_entries) != 1 or pg_entries[0][0].upper() != "PGPASSFILE":
        raise RuntimeError("database maintenance helper libpq environment is not sealed")
    try:
        expected = os.path.normcase(os.path.abspath(os.fspath(pgpassfile)))
        actual = os.path.normcase(os.path.abspath(pg_entries[0][1]))
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("database maintenance helper libpq environment is not sealed") from exc
    if actual != expected:
        raise RuntimeError("database maintenance helper libpq environment is not sealed")


__all__ = [
    "assert_maintenance_libpq_environment",
    "load_standalone_database_module",
    "resolve_generation_program",
]
