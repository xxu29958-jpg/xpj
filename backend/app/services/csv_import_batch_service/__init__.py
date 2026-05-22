"""CSV import batch service.

Public API used by ``routes/imports.py`` and ``routes/web_import_export.py``:

- ``create_csv_import_batch`` — parse uploaded CSV into a CsvImportBatch
  with one CsvImportRow per data line
- ``get_csv_import_batch`` — fetch a batch by public_id, scoped to tenant
- ``list_csv_import_rows`` — paginate rows of a batch
- ``apply_csv_import_batch`` — promote ``valid`` rows to Expense records
- ``build_csv_import_errors_csv`` — return a CSV string of failed rows

Constants ``MAX_CSV_IMPORT_ROWS``, ``APPLY_LEASE_MINUTES``,
``ROW_APPLY_LEASE_MINUTES``, ``DEFAULT_BATCH_FILE_NAME`` are also re-exported.

Internal layout (one concern per submodule):

- ``_common``        — constants only (no app imports beyond stdlib)
- ``_csv_io``        — file-name cleanup, row materialisation, count
                       refresh, error-CSV writer
- ``_lifecycle``     — create / get / list (the non-apply public API)
- ``_row_claim``     — row-level lease state machine (valid → applying
                       → applied / insert_failed, plus stale recovery)
- ``_apply_lease``   — batch-level lease state machine (parsed →
                       applying → applied / failed, plus finalize +
                       token-match check)
- ``_idempotency``   — row-level dedupe key + IntegrityError resolution
- ``_apply``         — the orchestrator that wires the lease + row
                       claim + insert + finalize + 3-branch rollback
                       ladder

Dependency rule: ``_common`` is a leaf; ``_csv_io`` depends on _common
only; ``_row_claim`` is independent of _csv_io but uses _common;
``_lifecycle`` depends on _csv_io; ``_apply_lease`` depends on
_row_claim + _csv_io and lazily on _lifecycle; ``_idempotency`` depends
on _apply_lease and lazily on _lifecycle; ``_apply`` sits on top.

The few cross-module lazy imports inside function bodies
(``_apply_lease`` → ``_lifecycle``, ``_idempotency`` → ``_lifecycle``)
are intentional — they keep ``_lifecycle`` as the entrypoint module
without creating an import-time cycle.

Four private helpers are re-exported because
``tests/test_csv_import_batches.py`` reaches into them to verify the
state machine directly:

  _claim_apply_lease
  _claim_csv_import_rows
  _refresh_claimed_csv_import_row
  _resolve_csv_import_idempotency_conflict
"""

from __future__ import annotations

from app.services.csv_import_batch_service._apply import apply_csv_import_batch
from app.services.csv_import_batch_service._apply_lease import (
    _claim_apply_lease,
)
from app.services.csv_import_batch_service._common import (
    APPLY_LEASE_MINUTES,
    DEFAULT_BATCH_FILE_NAME,
    MAX_CSV_IMPORT_ROWS,
    ROW_APPLY_LEASE_MINUTES,
)
from app.services.csv_import_batch_service._csv_io import build_csv_import_errors_csv
from app.services.csv_import_batch_service._idempotency import (
    _resolve_csv_import_idempotency_conflict,
)
from app.services.csv_import_batch_service._lifecycle import (
    create_csv_import_batch,
    get_csv_import_batch,
    list_csv_import_rows,
)
from app.services.csv_import_batch_service._row_claim import (
    _claim_csv_import_rows,
    _refresh_claimed_csv_import_row,
)

__all__ = [
    "APPLY_LEASE_MINUTES",
    "DEFAULT_BATCH_FILE_NAME",
    "MAX_CSV_IMPORT_ROWS",
    "ROW_APPLY_LEASE_MINUTES",
    "_claim_apply_lease",
    "_claim_csv_import_rows",
    "_refresh_claimed_csv_import_row",
    "_resolve_csv_import_idempotency_conflict",
    "apply_csv_import_batch",
    "build_csv_import_errors_csv",
    "create_csv_import_batch",
    "get_csv_import_batch",
    "list_csv_import_rows",
]
