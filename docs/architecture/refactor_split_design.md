# Refactor split design — deferred audit items

This document covers the three remaining "high severity" structural items
from the codebase audit that were too large to land safely in the same
session as the other 12 fixes:

- **S-003** — `csv_import_batch_service.py` (782 LOC) — extract the apply
  state machine from 22 free functions
- **S-009** — `owner_console_service.py` (694 LOC) — split the 7-line
  business surface into per-domain modules
- **S-011** — `routes/owner_console.py` (623 LOC, 32 endpoints) — split
  the single router along the same domain seams as S-009

Each section gives the current shape, the target layout, the commit
sequence, the risk inventory, and a verification checklist. The intent
is that any one of these three can be executed independently in a
dedicated session by following its plan.

---

## S-003 — CSV import apply state machine

### Current shape

`app/services/csv_import_batch_service.py` (782 LOC, 22 module-level
functions) implements the import-batch lifecycle as a free-function
graph clustered around one 187-line orchestrator (`apply_csv_import_batch`)
plus 12 helpers that read/write batch and row state:

```
apply_csv_import_batch              (158)  ← 187 LOC orchestrator
_claim_apply_lease                  (348)
_claim_csv_import_rows              (389)
_reset_claimed_csv_import_rows      (436)
_refresh_claimed_csv_import_row     (458)
_recover_stale_csv_import_rows      (479)
_mark_csv_import_apply_failed       (503)
_release_csv_import_apply_lease     (521)
_batch_apply_token_matches          (540)
_finalize_csv_import_apply_success  (557)
_resolve_csv_import_idempotency_conflict (581)
_csv_import_row_idempotency_key     (635)
_existing_csv_import_expense_id     (639)
_applying_row_count                 (757)
_remaining_importable_rows          (771)
```

The implicit state machine has these transitions on `CsvImportBatch.status`
and `CsvImportRow.status`:

```
Batch:   draft → applying → applied / failed
Row:     valid → applying → applied / insert_failed
```

Plus four lease tokens that protect the transitions from concurrent
applies: `CsvImportBatch.apply_token`, `CsvImportRow.apply_token`,
`CsvImportBatch.locked_until`, and the post-apply `applied_at` /
`last_error` audit fields.

The problem the audit flagged: the state model isn't named anywhere. A
new contributor has to read all 22 functions and the orchestrator's
`try / except AppError / except IntegrityError / except Exception` ladder
before they can reason about what state a batch is in after each step.

### Target shape

Two modules at the same path-prefix (parallel to the `database/` and
`expense_service/` packages we landed earlier):

```
app/services/csv_import_batch/
├── __init__.py        — re-exports the public API surface that
│                        routes/imports.py and routes/web_import_export.py
│                        already use:
│                          create_csv_import_batch
│                          get_csv_import_batch
│                          list_csv_import_rows
│                          apply_csv_import_batch
│                          build_csv_import_errors_csv
│
├── _lifecycle.py      — non-apply public API (create, get, list, errors CSV)
│
├── _apply.py          — the orchestrator: apply_csv_import_batch only,
│                        plus the small ApplyOutcome dataclass it returns.
│                        ~120 LOC after extracting helpers.
│
├── _apply_lease.py    — batch-level lease management:
│                          claim_apply_lease(db, *, tenant_id, public_id, apply_token)
│                          release_apply_lease(db, *, tenant_id, public_id, apply_token)
│                          mark_apply_failed(db, *, tenant_id, public_id, apply_token)
│                          finalize_apply_success(...)
│                          batch_apply_token_matches(...)
│                        ~90 LOC. All five share the same {tenant_id,
│                        public_id, apply_token} contract.
│
├── _row_claim.py      — row-level lease management:
│                          claim_rows(db, *, tenant_id, batch_id, batch_size, apply_token)
│                          reset_claimed_rows(...)
│                          refresh_claimed_row(...)
│                          recover_stale_rows(...)
│                          applying_row_count(...)
│                          remaining_importable_rows(...)
│                        ~110 LOC.
│
├── _idempotency.py    — duplicate-resolution path on IntegrityError:
│                          row_idempotency_key(batch, row) -> str
│                          existing_expense_id(db, *, tenant_id, idempotency_key)
│                          resolve_idempotency_conflict(db, *, tenant_id, public_id,
│                                                       row_ids, apply_token)
│                        ~70 LOC.
│
└── _csv_io.py         — pure I/O / encoding helpers:
                          build_errors_csv(batch_rows) -> str
                          row_from_parsed(batch, parsed)
                          clean_file_name(value)
                          refresh_batch_counts(db, batch)
                        ~80 LOC.
```

The orchestrator's body becomes a linear narration of named steps:

```python
def apply_csv_import_batch(db, *, tenant_id, public_id, batch_size):
    apply_token = str(uuid4())
    batch = lease.claim_apply_lease(db, tenant_id=tenant_id,
                                    public_id=public_id,
                                    apply_token=apply_token)
    claimed_row_ids: list[int] = []
    try:
        row_claim.recover_stale_rows(db, tenant_id=tenant_id, batch_id=batch.id,
                                     stale_before=now_utc() - LEASE_TTL)
        claimed_row_ids = row_claim.claim_rows(db, ...)
        batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
        _ensure_not_already_applying(db, batch, tenant_id, claimed_row_ids)
        inserted = _apply_claimed_rows(db, batch, claimed_row_ids, apply_token)
        remaining = lease.finalize_apply_success(db, batch=batch, ...)
        db.commit()
        return CsvImportApplyResponse(...)
    except AppError:
        _rollback_apply(db, claimed_row_ids, tenant_id, public_id, apply_token)
        raise
    except IntegrityError as exc:
        ...
    except Exception:
        ...
```

### Dependency boundaries

Subordinate modules have only one inbound direction (orchestrator
→ helpers); helpers do not call back into `_apply`. The package
`__init__.py` re-exports exactly the four-symbol public API
(`create_csv_import_batch`, `get_csv_import_batch`, `list_csv_import_rows`,
`apply_csv_import_batch`, `build_csv_import_errors_csv`).

External callers stay untouched — they import from
`app.services.csv_import_batch_service`, which we keep as the package
name (rename `csv_import_batch_service.py` → `csv_import_batch_service/`).

### Commit sequence

1. **Prep commit**: move every helper into the target submodule, but
   each helper still has its current name and current signature. The
   submodules re-export everything; `csv_import_batch_service/__init__.py`
   re-exports the public surface; `apply_csv_import_batch` still lives
   in one file with the same body. **Verification: zero behavior change,
   `test_csv_import_batches.py` 100% pass.**

2. **Strangle commit**: rewrite `apply_csv_import_batch` to call into the
   submodule helpers via the new names (drop the `_csv_import_` prefix
   that comes from the legacy flat namespace). **Verification: full
   pytest pass + the apply-state-machine acceptance tests in
   `test_csv_import_batches.py::test_csv_import_row_claim_recovers_stale_apply_after_batch_lease_expires`
   and `::test_csv_import_batch_apply_confirmed_hits_stats_export_and_filters`.**

3. **Optional polish commit**: extract `_apply_claimed_rows`,
   `_ensure_not_already_applying`, and `_rollback_apply` from the
   orchestrator body so the top-level function reads as one screen.

### Risks

| Risk | Mitigation |
|---|---|
| Subtle ordering bug: helpers expect to be called with the same `db.flush()` checkpoints as today | Step 1 keeps function bodies byte-identical. Step 2 is pure rename + import path change. |
| Idempotency conflict path is fragile (it touches three branches: AppError / IntegrityError / Exception) | Keep these three `except` blocks in the orchestrator unchanged through step 2 — only the helper *names* shift, not the control flow. |
| `_claim_apply_lease` currently calls `_batch_apply_token_matches` indirectly via the `.where(apply_token == ...)` clause; moving it under `_apply_lease.py` could hide that dependency | Add a one-line docstring on each lease helper stating its precondition (e.g. "caller must hold the apply_token returned by `claim_apply_lease`"). |
| `_existing_csv_import_expense_id` is also called from the test fixtures of `test_csv_import_batches.py` (verify with grep before moving) | Re-export from package `__init__` if it turns out to be public. |

### Verification checklist

- [ ] `test_csv_import_batches.py` all pass (28 tests; the file is one of
      the largest test modules in the repo)
- [ ] `test_import_export.py` all pass
- [ ] `routes/imports.py` and `routes/web_import_export.py` still import
      successfully (smoke-import via `from app.main import app`)
- [ ] `check_api_contract.py` snapshot unchanged
- [ ] No new `except Exception` introduced (audit baseline)
- [ ] Per-module LOC under 200 each

---

## S-009 + S-011 — owner_console split (paired)

These two are listed separately in the audit but share the same domain
boundaries, share the `BudgetStatusVM` / `ConsoleIndexVM` /
`RecurringOpsVM` / `LedgerConsoleVM` types, and break in unison —
landing one without the other leaves a temporary asymmetry (route
calls into a service that no longer exists at the expected path). Plan
them as one design, one PR, possibly two sequential commits inside that
PR.

### Current shape

```
app/services/owner_console_service.py   694 LOC, 36 module-level symbols
app/routes/owner_console.py             623 LOC, 32 route handlers
```

Both files cover the same 8 functional zones:

| Zone | Service symbols | Route endpoints |
|---|---|---|
| **index** | `get_index_vm`, `_budget_status_for_primary_ledger`, `ConsoleIndexVM`, `BudgetStatusVM` | `GET /owner` |
| **rule-applications audit** | `get_rule_application_audit`, `RuleApplicationAuditRow`, `RuleApplicationAuditVM` | `GET /owner/rule-applications` |
| **devices** | `get_devices`, `do_revoke_device`, `do_delete_device`, `do_rename_device` | `GET /owner/devices`, `POST .../revoke`, `POST .../rename`, `POST .../delete` |
| **pairing** | `do_create_pairing_code` | `GET /owner/pairing`, `POST /owner/pairing` |
| **upload-links** | `get_upload_links`, `do_create_upload_link`, `do_rotate_upload_link`, `do_revoke_upload_link`, `do_delete_upload_link`, `compose_public_upload_url` | `GET /owner/upload-links`, `POST .../`, `POST .../rotate`, `POST .../revoke`, `POST .../delete` |
| **diagnostics** | — (route reads from sibling services) | `GET /owner/diagnostics` |
| **settings** | (route reads `runtime_settings_service` directly) | `GET /owner/settings`, `GET /owner/settings/public-base-url`, `POST .../`, `GET /owner/settings/security`, `GET /owner/settings/api`, `GET /owner/settings/about` |
| **backups + migration-readiness** | (route reads `backup_service` + `migration_readiness_service`) | `GET /owner/backups`, `POST .../`, `GET /owner/migration-readiness`, `POST .../pre-v1-backup` |
| **recurring ops summary** | `get_recurring_ops`, `_count_recurring`, `RecurringOpsVM` | (consumed by `get_index_vm` only) |
| **ledger console** | `list_console_ledgers`, `list_manageable_console_ledgers`, `list_console_ledger_choices`, `do_create_ledger`, `_ledger_console_rows`, `LedgerConsoleVM`, `LedgerHealthVM`, `list_ledger_health` | (consumed by `owner_ledgers.py` route, not by `owner_console.py`) |

### Target shape

#### Service side — `app/services/owner_console/` package

```
app/services/owner_console/
├── __init__.py            — re-exports the public surface that
│                            owner_console.py and owner_ledgers.py use
│
├── _index.py              — index VM aggregation
│                            (~90 LOC, dominates by 7-card composition;
│                             stays large by intention, see §Risks)
│
├── _devices.py            — device CRUD (~70 LOC)
│
├── _upload_links.py       — upload-link CRUD + URL composition (~80 LOC)
│
├── _pairing.py            — pairing code creation (~40 LOC)
│
├── _recurring_ops.py      — recurring summary used by _index (~80 LOC)
│
├── _rule_audit.py         — rule application batch audit view (~70 LOC)
│
├── _ledger_console.py     — ledger console rows / choices / create
│                            (the part that `owner_ledgers.py` route
│                             imports, not owner_console.py route)
│
└── _common.py             — _amount_yuan, _owner_ledger_ids,
                              _managed_console_ledger_ids,
                              _expense_status_count,
                              _active_upload_link_count,
                              get_owner_account_id, get_default_ledger_id
                              (shared low-level lookups, ~80 LOC)
```

Public re-exports stay flat at `app.services.owner_console_service` so
no caller has to change:

```python
# app/services/owner_console/__init__.py
from app.services.owner_console._index import get_index_vm, ConsoleIndexVM, BudgetStatusVM
from app.services.owner_console._devices import (
    get_devices, do_revoke_device, do_delete_device, do_rename_device, DeviceSummary,
)
# ...
__all__ = [<full original list of 18 public symbols>]
```

(Rename the file `owner_console_service.py` → directory
`owner_console_service/` so the import path
`app.services.owner_console_service` is preserved.)

#### Route side — `app/routes/owner_console/` package

```
app/routes/owner_console/
├── __init__.py            — defines the single APIRouter and the
│                            shared dependencies (LocalOnly, _base,
│                            _format_owner_datetime, etc.) that every
│                            sub-router uses. Includes the sub-routers.
│
├── _index.py              — GET /owner, GET /owner/rule-applications
│
├── _devices.py            — 4 device endpoints
│
├── _upload_links.py       — 5 upload-link endpoints
│
├── _pairing.py            — 2 pairing endpoints
│
├── _diagnostics.py        — GET /owner/diagnostics
│
├── _settings.py           — 6 settings endpoints
│
└── _backups.py            — 4 backup + migration-readiness endpoints
```

Each sub-router creates its own `APIRouter` with the same `/owner`
prefix; the package `__init__.py` includes them on a parent router that
gets handed to `app/main.py`. This is the standard FastAPI mounting
pattern.

`main.py` still has the single line
`app.include_router(owner_console.router)` — the variable just resolves
to the package's top-level router now.

### Commit sequence

1. **Service split**: introduce `owner_console_service/` directory with
   the per-domain submodules. The submodules import each other only via
   `_common`. `__init__.py` re-exports the full original surface.
   `owner_console.py` route is untouched. **Verification: full pytest
   pass — focus on
   `test_owner_console*.py` (4 files, ~50 tests).**

2. **Route split**: introduce `owner_console/` route package. Each
   sub-router has its share of endpoints. `main.py` import / include
   line is updated to the package's top-level router.
   **Verification: full pytest pass + `check_api_contract.py` snapshot
   unchanged (no operation IDs renamed, no paths moved).**

### Risks

| Risk | Mitigation |
|---|---|
| `get_index_vm` orchestrates 7 sibling services with broad exception swallowing (post-S-006 each `except Exception` is `# noqa: BLE001` annotated). Splitting per-card into separate modules tempts narrowing the catches. | Keep the broad catches in `_index.py`; do not chase narrower types in this refactor. The dashboard-card invariant ("one failed card must never 500 the index") is documented; honour it. |
| `_owner_ledger_ids` and `_managed_console_ledger_ids` are read by 4 different domain modules. Naïvely placing them under `_common` is fine; placing them under any single domain creates a back-import. | They go in `_common.py`. No domain submodule imports another domain submodule directly — all cross-domain access goes through `_common`. |
| Route package `__init__.py` must avoid the *route-discovery* mistake where some endpoints get mounted twice (which we just hit in S-005 cleanup). | Acceptance test: enumerate `app.routes` via `app.routes` after restart, assert exactly 32 endpoints under `/owner/*`. The OpenAPI snapshot drift check already covers this — any duplicate operation ID makes the diff fail. |
| `LedgerConsoleVM` types are shared between `owner_console.py` (which does NOT use them) and `owner_ledgers.py` (which DOES use them). They're in `owner_console_service.py` today purely by accident. | Move them into `owner_console_service/_ledger_console.py` and re-export from package `__init__`. `owner_ledgers.py` route's import path is unchanged because re-export preserves the symbol at `app.services.owner_console_service.LedgerConsoleVM`. |
| Tests reach into private helpers (`_budget_status_for_primary_ledger`, etc.) via the module path | grep `from app.services.owner_console_service import _` before the split; any private symbol with external test refs gets re-exported through the package `__init__`. |

### Verification checklist

- [ ] All 4 owner-console test files pass:
      `test_owner_console.py`, `test_owner_console_backups.py`,
      `test_owner_console_dq_snapshot.py`, `test_owner_console_ledger_health.py`,
      `test_owner_console_members.py`, `test_owner_console_migration_readiness.py`,
      `test_owner_console_recurring_ops.py`
- [ ] `owner_ledgers.py` tests pass (imports `LedgerConsoleVM` etc.)
- [ ] `check_api_contract.py` snapshot unchanged
- [ ] No file in `owner_console/` or `owner_console_service/` exceeds 200 LOC
- [ ] `_audit_service_graph.py` shows no new cycles

### Why not unify with `admin_service`?

The audit noted `owner_console_service` and `admin_service` both define
`DeviceSummary` / `UploadLinkSummary` dataclasses with nearly identical
fields. Tempting target for a 3-way merge. Out of scope for this
split — would couple two refactor PRs together. Land the
`owner_console` split first, then a follow-up commit can de-duplicate
the dataclasses.

---

## Sequencing across all three

Suggested order across sessions, lowest-risk first:

1. **Session A** — S-009 service split (Commit 1 above)
2. **Session A** — S-011 route split (Commit 2 above, same PR)
3. **Session B** — S-003 csv_import staged commits

The two owner_console pieces are paired; doing them in one PR means the
reviewer only has to validate one domain boundary set. S-003 is
genuinely independent and benefits from a dedicated session because the
state-machine semantics need careful single-step review.

## Shared verification habits

For every split commit:

1. Run the originally-affected test file in isolation first
   (`pytest -q tests/test_csv_import_batches.py` or
   `tests/test_owner_console.py`)
2. Run the full backend suite (currently 614 tests, ~60s with the
   in-memory SQLite setup)
3. Run `python scripts/check_api_contract.py` — the OpenAPI snapshot
   must stay byte-identical (these are internal refactors, not API
   changes)
4. Run `python scripts/_audit_service_graph.py` — confirm no new
   SCCs introduced and no new ≥7 fanout modules
5. Run `python scripts/_audit_codebase.py | head -60` — confirm the
   "module surface area top 30" no longer features the split target

If any of these regress, revert the commit and split it smaller — none
of these three refactors needs to land in one heroic patch.
