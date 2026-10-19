"""Retain accepted funds outcomes without repeated account or envelope histories."""
import sqlalchemy as sa
from alembic import op

revision = "20261019_0005"
down_revision = "20261019_0004"
branch_labels = None
depends_on = None


def _set_revision(expected, target):
    result = op.get_bind().execute(sa.text(
        "UPDATE dataset_authority SET schema_revision=:target WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"),
        {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the funds receipt migration edge")


def upgrade():
    # Never expire the key or reconstruct an old outcome from today's balances.
    # Only duplicated query collections are removed; accepted scalars and all
    # request fingerprints, identities, statuses and timestamps remain intact.
    op.execute("""
UPDATE api_idempotency_keys
SET response_body = ((response_body::jsonb - ARRAY['movements','fee_obligations','prior_repayments','credit_applications'])
    || jsonb_build_object('receipt_revision', 1))::json
WHERE status='succeeded' AND resource_type='financial_account'
    AND jsonb_typeof(response_body::jsonb)='object' AND response_body::jsonb ? 'public_id';
UPDATE api_idempotency_keys
SET response_body = ((response_body::jsonb - ARRAY['accounts','purposes','months','notices'])
    || '{"receipt_revision": 1,"accounts": [],"purposes": [],"months": [],"notices": []}'::jsonb)::json
WHERE status='succeeded' AND operation='save_envelopes' AND resource_type='envelope_book'
    AND jsonb_typeof(response_body::jsonb)='object' AND response_body::jsonb ? 'row_version';
""")
    _set_revision(down_revision, revision)


def downgrade():
    # Older readers default omitted account collections and accept empty envelope
    # collections. Restoring duplicated historical views would invent evidence.
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    if bind.scalar(sa.text("""
SELECT EXISTS (SELECT 1 FROM api_idempotency_keys
 WHERE status='succeeded' AND (
   (resource_type='financial_account' AND response_body::jsonb ?|
       ARRAY['movements','fee_obligations','prior_repayments','credit_applications'])
   OR (resource_type='envelope_book' AND operation='save_envelopes' AND
       (response_body::jsonb->'accounts' <> '[]'::jsonb OR response_body::jsonb->'purposes' <> '[]'::jsonb
        OR response_body::jsonb->'months' <> '[]'::jsonb OR response_body::jsonb->'notices' <> '[]'::jsonb))))
""")):
        raise RuntimeError("funds receipts still retain duplicated query history")
