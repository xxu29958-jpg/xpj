"""Durable C07 receipt publication, repair, and startup readiness gate."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from app.database._c07_contract import (
    C07_CEREMONY_ID_KEY,
    C07_FRESH_CEREMONY_ID,
    C07_LIFECYCLE_FRESH,
    C07_LIFECYCLE_PENDING,
    C07_LIFECYCLE_READY,
    C07_LIFECYCLE_STATE_KEY,
    C07_RECEIPT_SHA256_KEY,
    C07_TARGET_REVISION,
    RECEIPT_DIR,
    SHA256_PATTERN,
    C07CeremonyError,
    C07ReceiptRepairRequiredError,
    canonical_json,
    canonical_uuid,
    sha256_bytes,
)
from app.database._c07_execution import (
    _money_shape,
    _revision,
    _revision_includes_c07,
)
from app.database._c07_receipt_validation import (
    validate_receipt_against_live_database,
)
from app.money_contract import (
    MONEY_CONTRACT_PHASE_C07,
    MONEY_CONTRACT_PHASE_KEY,
)
from app.services.secure_file import (
    hold_protected_file_for_read,
    publish_protected_file_no_replace,
    write_protected_file_exclusive,
)


def c07_receipt_directory(path: Path | None = None) -> Path:
    directory = path or RECEIPT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _upsert_meta(connection, key: str, value: str) -> None:
    connection.execute(
        text(
            "INSERT INTO app_meta (key, value, updated_at) "
            "VALUES (:key, :value, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
            "updated_at = EXCLUDED.updated_at"
        ),
        {"key": key, "value": value},
    )


def _receipt_paths(
    ceremony_id: str,
    *,
    directory: Path,
) -> tuple[Path, Path]:
    final = directory / f"ticketbox-c07-{ceremony_id}.json"
    temporary = directory / f".ticketbox-c07-{ceremony_id}.pending"
    if final.exists() or temporary.exists():
        raise C07CeremonyError(
            "C07 receipt path already exists; use repair, not overwrite"
        )
    return temporary, final


def _write_receipt_pending(
    *,
    temporary: Path,
    receipt: dict[str, object],
    record_identity: Callable[[str, bytes], None],
) -> tuple[str, bytes]:
    payload = canonical_json(receipt).encode("utf-8")
    sha256 = sha256_bytes(payload)
    # Publish the exact candidate identity to the transaction owner before
    # the first filesystem mutation.  Any write/read-after-write exception
    # can then be reconciled against a fresh database observation.
    record_identity(sha256, payload)
    try:
        write_protected_file_exclusive(temporary, payload.decode("utf-8"))
        with hold_protected_file_for_read(temporary) as protected:
            persisted = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07CeremonyError(
            "unable to durably stage the C07 receipt"
        ) from exc
    if persisted != payload:
        raise C07CeremonyError(
            "staged C07 receipt failed read-after-write verification"
        )
    return sha256, payload


def _publish_receipt(
    temporary: Path,
    final: Path,
    expected: bytes,
) -> None:
    try:
        publish_protected_file_no_replace(temporary, final)
        with hold_protected_file_for_read(final) as protected:
            persisted = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 schema committed but receipt publication failed; keep "
            "writers frozen and run the publication repair"
        ) from exc
    if persisted != expected:
        raise C07ReceiptRepairRequiredError(
            "C07 schema committed but published receipt bytes differ; "
            "keep writers frozen"
        )


def _finalize_ready_marker(
    source_engine: Engine,
    *,
    ceremony_id: str,
    receipt_sha256: str,
    receipt_payload: bytes,
    alembic_config: Config | None = None,
) -> None:
    with source_engine.begin() as connection:
        try:
            current_revision = _revision(connection)
            includes_c07 = _revision_includes_c07(
                current_revision,
                alembic_config=alembic_config,
            )
        except C07CeremonyError as exc:
            raise C07ReceiptRepairRequiredError(
                "C07 receipt finalization cannot verify revision ancestry"
            ) from exc
        if not includes_c07:
            raise C07ReceiptRepairRequiredError(
                "C07 receipt exists but database revision does not include C07"
            )
        stored = dict(
            connection.execute(
                text(
                    "SELECT key, value FROM app_meta "
                    "WHERE key IN (:ceremony_key, :sha_key, :state_key)"
                ),
                {
                    "ceremony_key": C07_CEREMONY_ID_KEY,
                    "sha_key": C07_RECEIPT_SHA256_KEY,
                    "state_key": C07_LIFECYCLE_STATE_KEY,
                },
            ).all()
        )
        if (
            stored.get(C07_CEREMONY_ID_KEY) != ceremony_id
            or stored.get(C07_RECEIPT_SHA256_KEY) != receipt_sha256
            or stored.get(C07_LIFECYCLE_STATE_KEY) != C07_LIFECYCLE_PENDING
        ):
            raise C07ReceiptRepairRequiredError(
                "C07 database receipt markers do not match the staged receipt"
            )
        validate_receipt_against_live_database(
            connection,
            payload=receipt_payload,
            ceremony_id=ceremony_id,
            receipt_sha256=receipt_sha256,
        )
        _upsert_meta(
            connection,
            C07_LIFECYCLE_STATE_KEY,
            C07_LIFECYCLE_READY,
        )


def _read_lifecycle_values(
    connection,
    *,
    alembic_config: Config | None = None,
) -> dict[str, str] | None:
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" not in tables:
        return None
    try:
        current_revision = _revision(connection)
        includes_c07 = _revision_includes_c07(
            current_revision,
            alembic_config=alembic_config,
        )
    except C07CeremonyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 lifecycle ancestry is not verifiable"
        ) from exc
    if not includes_c07:
        return None
    if "app_meta" not in tables:
        raise C07ReceiptRepairRequiredError(
            "C07 target is missing its lifecycle metadata table"
        )
    return dict(
        connection.execute(
            text(
                "SELECT key, value FROM app_meta "
                "WHERE key IN "
                "(:phase_key, :ceremony_key, :sha_key, :state_key)"
            ),
            {
                "phase_key": MONEY_CONTRACT_PHASE_KEY,
                "ceremony_key": C07_CEREMONY_ID_KEY,
                "sha_key": C07_RECEIPT_SHA256_KEY,
                "state_key": C07_LIFECYCLE_STATE_KEY,
            },
        ).all()
    )


def _ready_receipt_identity(
    values: dict[str, str],
) -> tuple[str, str] | None:
    if values.get(MONEY_CONTRACT_PHASE_KEY) != MONEY_CONTRACT_PHASE_C07:
        raise C07ReceiptRepairRequiredError(
            "C07 target is missing its money-contract phase marker"
        )
    state = values.get(C07_LIFECYCLE_STATE_KEY)
    if state == C07_LIFECYCLE_FRESH:
        if values.get(C07_CEREMONY_ID_KEY) != C07_FRESH_CEREMONY_ID:
            raise C07ReceiptRepairRequiredError(
                "C07 fresh-install marker is inconsistent"
            )
        return None
    if state != C07_LIFECYCLE_READY:
        raise C07ReceiptRepairRequiredError(
            "C07 target is not receipt-ready; keep HTTP writers closed "
            "and run repair"
        )
    ceremony_id = canonical_uuid(
        values.get(C07_CEREMONY_ID_KEY),
        label="stored ceremony_id",
    )
    receipt_sha256 = values.get(C07_RECEIPT_SHA256_KEY)
    if (
        not isinstance(receipt_sha256, str)
        or SHA256_PATTERN.fullmatch(receipt_sha256) is None
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 receipt digest marker is invalid"
        )
    return ceremony_id, receipt_sha256


def _verify_receipt_artifact(
    connection,
    *,
    ceremony_id: str,
    receipt_sha256: str,
    receipt_dir: Path | None,
) -> None:
    directory = receipt_dir or RECEIPT_DIR
    path = directory / f"ticketbox-c07-{ceremony_id}.json"
    try:
        with hold_protected_file_for_read(path) as protected:
            payload = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt is unavailable"
        ) from exc
    if sha256_bytes(payload) != receipt_sha256:
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt digest mismatch"
        )
    validate_receipt_against_live_database(
        connection,
        payload=payload,
        ceremony_id=ceremony_id,
        receipt_sha256=receipt_sha256,
    )


def assert_c07_lifecycle_ready(
    source_engine: Engine,
    *,
    receipt_dir: Path | None = None,
    production_projection_path: Path | None = None,
    production_authority_required: bool = False,
    alembic_config: Config | None = None,
) -> None:
    """Fail closed when C07 committed but its durable receipt is incomplete."""

    from app.database._c07_production_ready import assert_c07_production_ready

    with source_engine.connect() as connection:
        current_revision = _revision(connection)
        if assert_c07_production_ready(
            connection,
            projection_path=production_projection_path,
            expected_revision=current_revision,
        ):
            try:
                if not _revision_includes_c07(
                    current_revision,
                    alembic_config=alembic_config,
                ):
                    raise C07CeremonyError(
                        "production authority does not include the C07 revision"
                    )
                _money_shape(
                    connection,
                    target_revision=C07_TARGET_REVISION,
                )
            except C07CeremonyError as exc:
                raise C07ReceiptRepairRequiredError(
                    "C07 production database live shape is invalid"
                ) from exc
            return
        if production_authority_required:
            raise C07ReceiptRepairRequiredError(
                "C07 installed-host database lacks its production "
                "database marker and SYSTEM runtime projection"
            )
        values = _read_lifecycle_values(
            connection,
            alembic_config=alembic_config,
        )
        if values is None:
            return
        identity = _ready_receipt_identity(values)
        if identity is None:
            return
        ceremony_id, receipt_sha256 = identity
        _verify_receipt_artifact(
            connection,
            ceremony_id=ceremony_id,
            receipt_sha256=receipt_sha256,
            receipt_dir=receipt_dir,
        )


def _pending_receipt_identity(
    connection,
    *,
    alembic_config: Config | None = None,
) -> tuple[str, str]:
    try:
        current_revision = _revision(connection)
        includes_c07 = _revision_includes_c07(
            current_revision,
            alembic_config=alembic_config,
        )
    except C07CeremonyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 receipt repair cannot verify revision ancestry"
        ) from exc
    if not includes_c07:
        raise C07ReceiptRepairRequiredError(
            "C07 receipt repair requires a revision containing C07"
        )
    values = dict(
        connection.execute(
            text(
                "SELECT key, value FROM app_meta "
                "WHERE key IN (:ceremony_key, :sha_key, :state_key)"
            ),
            {
                "ceremony_key": C07_CEREMONY_ID_KEY,
                "sha_key": C07_RECEIPT_SHA256_KEY,
                "state_key": C07_LIFECYCLE_STATE_KEY,
            },
        ).all()
    )
    if values.get(C07_LIFECYCLE_STATE_KEY) != C07_LIFECYCLE_PENDING:
        raise C07CeremonyError(
            "C07 receipt repair is only valid from pending state"
        )
    ceremony_id = canonical_uuid(
        values.get(C07_CEREMONY_ID_KEY),
        label="stored ceremony_id",
    )
    expected_sha = values.get(C07_RECEIPT_SHA256_KEY)
    if (
        not isinstance(expected_sha, str)
        or SHA256_PATTERN.fullmatch(expected_sha) is None
    ):
        raise C07CeremonyError("C07 pending receipt digest is invalid")
    return ceremony_id, expected_sha


def _read_repair_candidate(
    *,
    directory: Path,
    ceremony_id: str,
    expected_sha: str,
) -> tuple[Path, Path, Path, bytes]:
    temporary = directory / f".ticketbox-c07-{ceremony_id}.pending"
    final = directory / f"ticketbox-c07-{ceremony_id}.json"
    candidate = final if final.is_file() else temporary
    try:
        with hold_protected_file_for_read(candidate) as protected:
            payload = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 pending receipt artifact is unavailable"
        ) from exc
    if sha256_bytes(payload) != expected_sha:
        raise C07ReceiptRepairRequiredError(
            "C07 pending receipt artifact digest mismatch"
        )
    return temporary, final, candidate, payload


def _remove_matching_pending(
    *,
    temporary: Path,
    payload: bytes,
) -> None:
    if not temporary.exists():
        return
    try:
        with hold_protected_file_for_read(temporary) as protected:
            temporary_payload = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 published receipt has an unverifiable pending artifact"
        ) from exc
    if temporary_payload != payload:
        raise C07ReceiptRepairRequiredError(
            "C07 published receipt has a conflicting pending artifact"
        )
    temporary.unlink()


def repair_c07_receipt_publication(
    source_engine: Engine,
    *,
    receipt_dir: Path | None = None,
    alembic_config: Config | None = None,
) -> Path:
    """Finish only the post-commit receipt publication; never rerun DDL."""

    directory = c07_receipt_directory(receipt_dir)
    with source_engine.connect() as connection:
        ceremony_id, expected_sha = _pending_receipt_identity(
            connection,
            alembic_config=alembic_config,
        )
        temporary, final, candidate, payload = _read_repair_candidate(
            directory=directory,
            ceremony_id=ceremony_id,
            expected_sha=expected_sha,
        )
        validate_receipt_against_live_database(
            connection,
            payload=payload,
            ceremony_id=ceremony_id,
            receipt_sha256=expected_sha,
        )
    if candidate == temporary:
        _publish_receipt(temporary, final, payload)
    _remove_matching_pending(temporary=temporary, payload=payload)
    _finalize_ready_marker(
        source_engine,
        ceremony_id=ceremony_id,
        receipt_sha256=expected_sha,
        receipt_payload=payload,
        alembic_config=alembic_config,
    )
    return final
