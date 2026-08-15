"""Run the source-tree C07 action through the frozen generation program."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _load_production_module() -> ModuleType:
    """Load the production action without importing ``app.database``.

    Importing a normal ``app.database.*`` submodule executes the legacy package
    facade first, which materialises the runtime engine from application
    settings.  The host migration path must stay independent from that facade.
    """

    name = "_ticketbox_c07_production_migration"
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    path = (
        BACKEND_ROOT
        / "app"
        / "database"
        / "_c07_production_migration.py"
    )
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("production migration module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loaded = False
    try:
        spec.loader.exec_module(module)
        loaded = True
    finally:
        if not loaded:
            sys.modules.pop(name, None)
    return module


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-migrate", action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--generation-program-path", type=Path, required=True)
    parser.add_argument("--expected-generation-program-sha256", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--target-revision", required=True)
    return parser.parse_args(argv)


def _run_production(args: argparse.Namespace) -> dict[str, object]:
    production = _load_production_module()
    required = {
        "--database-url": args.database_url,
        "--pgpassfile": args.pgpassfile,
        "--generation-program-path": args.generation_program_path,
        "--expected-generation-program-sha256": (
            args.expected_generation_program_sha256
        ),
        "--operation-id": args.operation_id,
        "--source-revision": args.source_revision,
        "--target-revision": args.target_revision,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise production.C07ProductionMigrationError(
            "--production-migrate requires " + ", ".join(missing)
        )
    context = production.read_production_migration_context(sys.stdin.buffer)
    return production.run_production_migration_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        generation_program_path=args.generation_program_path,
        expected_generation_program_sha256=(
            args.expected_generation_program_sha256
        ),
        operation_id=args.operation_id,
        source_revision=args.source_revision,
        target_revision=args.target_revision,
        migration_context=context,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = _run_production(args)
    except (
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
