"""Compile the immutable installed-database generation program at build time."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROGRAM_FILENAME = "DATABASE_GENERATION_PROGRAM.json"
PROGRAM_SCHEMA = "ticketbox-database-generation-program-v1"
BASE_SOURCE = "base"


class GenerationProgramBuildError(RuntimeError):
    """The checked-in migration graph cannot produce one supported program."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _postcondition(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise GenerationProgramBuildError(
            f"cannot parse migration module {path.name}"
        ) from exc
    return (
        "assert_postcondition"
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "assert_postcondition"
            for node in tree.body
        )
        else None
    )


@contextmanager
def _backend_import_root(root: Path) -> Iterator[None]:
    original = list(sys.path)
    sys.path.insert(0, str(root))
    try:
        yield
    finally:
        sys.path[:] = original


def compile_program(backend_root: Path) -> dict[str, object]:
    root = backend_root.resolve(strict=True)
    versions_root = (root / "migrations" / "versions").resolve(strict=True)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    with _backend_import_root(root):
        scripts = ScriptDirectory.from_config(config)
        heads = tuple(scripts.get_heads())
        bases = tuple(scripts.get_bases())
        if len(heads) != 1 or len(bases) != 1:
            raise GenerationProgramBuildError(
                "generation program requires one Alembic base and head"
            )
        target_revision = heads[0]
        forward = tuple(
            reversed(tuple(scripts.iterate_revisions(target_revision, "base")))
        )

    with _backend_import_root(root):
        from app.database._c07_maintenance_plan import (
            C07_TARGET_REVISION,
            build_c07_revision_contract,
        )

        previous: str | None = None
        revisions: list[dict[str, object]] = []
        c07_count = 0
        for revision in forward:
            revision_id = str(revision.revision)
            module_path = Path(str(revision.path)).resolve(strict=True)
            if (
                module_path.parent != versions_root
                or revision.down_revision != previous
                or revision.dependencies is not None
            ):
                raise GenerationProgramBuildError(
                    "generation program is not one linear packaged chain"
                )
            module_sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest()
            context = None
            executor = "managed_postgres_v1"
            if revision_id == C07_TARGET_REVISION:
                contract = build_c07_revision_contract(
                    module_path=module_path,
                    module_sha256=module_sha256,
                    source_revision=str(revision.down_revision),
                    target_revision=revision_id,
                )
                context = contract.context
                executor = "c07_money_bigint_v1"
                c07_count += 1
            revisions.append(
                {
                    "context": context,
                    "down_revision": previous,
                    "executor": executor,
                    "module_path": module_path.relative_to(root).as_posix(),
                    "module_sha256": module_sha256,
                    "postcondition": _postcondition(module_path),
                    "revision": revision_id,
                }
            )
            previous = revision_id

    if (
        not revisions
        or revisions[0]["revision"] != bases[0]
        or previous != target_revision
        or c07_count != 1
        or revisions[-1]["postcondition"] != "assert_postcondition"
    ):
        raise GenerationProgramBuildError(
            "generation program does not cover one qualified base-to-head chain"
        )
    return {
        "revisions": revisions,
        "schema": PROGRAM_SCHEMA,
        "source_revision": BASE_SOURCE,
        "target_revision": target_revision,
    }


def write_program(*, backend_root: Path, output: Path) -> str:
    if output.name != PROGRAM_FILENAME:
        raise GenerationProgramBuildError(
            f"generation program output must be named {PROGRAM_FILENAME}"
        )
    payload = _canonical_json(compile_program(backend_root))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(write_program(backend_root=args.backend_root, output=args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
