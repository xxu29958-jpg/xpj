# Schema migrations

v1.1 (Batch 3) adopts **Alembic** for forward-only schema changes.
Pre-v1.1 column additions live in `app/database/_migrations/` and stay
there — they're idempotent ALTER + index creation and remain the boot
path for existing DBs. New tables and columns starting in v1.1 ship
as Alembic revisions instead.

## Quick reference

Run from `backend/` with the project venv active:

```
.venv/Scripts/alembic upgrade head                                # apply pending
.venv/Scripts/alembic revision --autogenerate -m "describe change"  # create revision
.venv/Scripts/alembic current                                     # which revision are we at
```

`init_db()` stamps the baseline revision on the first startup of a
fresh DB so you don't need a separate `alembic stamp` step. Existing
production DBs are stamped to the baseline automatically.

## Authoring a revision

1. Edit the SQLAlchemy model (or add a new one) under `app/models/`.
2. Run `alembic revision --autogenerate -m "<short summary>"`.
3. Review the generated file. Hand-edit when:
   - Adding indexes that aren't auto-detected.
   - Backfilling data (must be inside `op.execute(...)`).
   - Renaming a column (Alembic's autogen generates drop+add — that
     destroys data; rename it explicitly with `op.alter_column`).
4. Run `alembic upgrade head` locally against a copy of prod data.
5. Land the revision file together with the model change in one PR.

## Downgrades

The baseline revision intentionally has no `downgrade`. Subsequent
revisions should generally implement `downgrade` for development
convenience, but production never runs `downgrade` — restore from a
pre-migration backup instead.
