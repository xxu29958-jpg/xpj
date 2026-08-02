"""Run or repair the ADR-0073 C07 BIGINT deployment ceremony.

The live migration is deliberately unavailable through ordinary backend
startup.  A host coordinator must stop the backend while holding its lifecycle
lock, write the protected writer-freeze proof, and provide an empty isolated
restore database.  This command never creates or clears the restore database.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
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


def _load_isolated_module() -> ModuleType:
    return importlib.import_module("app.database._c07_ceremony")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--run", action="store_true")
    operation.add_argument("--repair-receipt", action="store_true")
    operation.add_argument("--production-migrate", action="store_true")
    parser.add_argument("--writer-freeze-proof", type=Path)
    parser.add_argument("--release-identity")
    parser.add_argument("--postgres-data-directory", type=Path)
    parser.add_argument(
        "--restore-url-env",
        default="C07_RESTORE_URL",
    )
    parser.add_argument("--database-url")
    parser.add_argument("--pgpassfile", type=Path)
    parser.add_argument("--operation-id")
    parser.add_argument("--source-revision")
    parser.add_argument("--target-revision")
    return parser.parse_args(argv)


def _run(args: argparse.Namespace, ceremony: ModuleType) -> Path:
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.database._core import _postgres_connect_args, engine

    if (
        args.writer_freeze_proof is None
        or args.release_identity is None
        or args.postgres_data_directory is None
    ):
        raise ceremony.C07CeremonyError(
            "--run requires --writer-freeze-proof, --release-identity and "
            "--postgres-data-directory"
        )
    restore_url = os.environ.get(args.restore_url_env, "")
    if not restore_url:
        raise ceremony.C07CeremonyError(
            f"isolated restore URL is missing from {args.restore_url_env}"
        )
    host = ceremony.read_host_freeze_evidence(
        args.writer_freeze_proof.absolute(),
        expected_release_identity=args.release_identity,
        expected_parent_pid=os.getppid(),
    )
    source_url = get_settings().database_url
    restore_engine = create_engine(
        restore_url,
        connect_args=_postgres_connect_args(restore_url),
        pool_pre_ping=True,
        future=True,
    )
    engine.dispose()
    try:
        return ceremony.run_c07_bigint_ceremony(
            source_engine=engine,
            source_url=source_url,
            restore_engine=restore_engine,
            restore_url=restore_url,
            host_evidence=host,
            postgres_data_directory=args.postgres_data_directory.absolute(),
        )
    finally:
        restore_engine.dispose()


def _repair_receipt(ceremony: ModuleType) -> Path:
    from app.database._core import engine

    return ceremony.repair_c07_receipt_publication(engine)


def _run_production(args: argparse.Namespace) -> dict[str, object]:
    production = _load_production_module()
    required = {
        "--database-url": args.database_url,
        "--pgpassfile": args.pgpassfile,
        "--operation-id": args.operation_id,
        "--source-revision": args.source_revision,
        "--target-revision": args.target_revision,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise production.C07ProductionMigrationError(
            "--production-migrate requires " + ", ".join(missing)
        )
    if any(
        value is not None
        for value in (
            args.writer_freeze_proof,
            args.release_identity,
            args.postgres_data_directory,
        )
    ):
        raise production.C07ProductionMigrationError(
            "--production-migrate does not accept isolated-test arguments"
        )
    context = production.read_production_migration_context(sys.stdin.buffer)
    return production.run_production_migration_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        operation_id=args.operation_id,
        source_revision=args.source_revision,
        target_revision=args.target_revision,
        migration_context=context,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.production_migrate:
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
    ceremony = _load_isolated_module()
    try:
        path = (
            _run(args, ceremony)
            if args.run
            else _repair_receipt(ceremony)
        )
    except ceremony.C07ReceiptRepairRequiredError as exc:
        print(f"REPAIR_REQUIRED: {exc}")
        return 2
    except (
        ceremony.C07CeremonyError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(f"READY: {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
