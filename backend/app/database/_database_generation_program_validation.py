"""Read-only validation owner for one build-owned generation program."""

from __future__ import annotations

from pathlib import Path

from app.database._database_generation_program import (
    BASE_SOURCE,
    DatabaseGenerationProgramError,
    load_database_generation_program,
)

VALIDATION_SCHEMA = "ticketbox-database-generation-program-validation-v2"


class DatabaseGenerationProgramValidationError(RuntimeError):
    """The frozen helper cannot prove the supplied generation program."""


def validate_database_generation_program(
    *,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
) -> dict[str, object]:
    try:
        program = load_database_generation_program(
            path=generation_program_path,
            expected_sha256=expected_generation_program_sha256,
        )
    except DatabaseGenerationProgramError as exc:
        raise DatabaseGenerationProgramValidationError(
            "database generation program validation failed"
        ) from exc
    return {
        "schema": VALIDATION_SCHEMA,
        "source_revision": BASE_SOURCE,
        "target_revision": program.target_revision,
        "revision_count": len(program.revisions),
        "generation_program_sha256": program.payload_sha256,
    }


__all__ = [
    "DatabaseGenerationProgramValidationError",
    "validate_database_generation_program",
]
