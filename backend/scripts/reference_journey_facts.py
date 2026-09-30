"""Read the actual reference owners and financial invariants in the isolated ledger."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense
from app.models.catalog import CategoryPreference, MerchantAlias, MerchantCatalog, Tag, TagMutationUndoGroup
from app.models.classification import CategoryRule, RuleApplicationBatch, RuleApplicationChange
from app.models.saved_view import SavedView


def facts(ledger_id):
    with SessionLocal() as db:
        def rows(model):
            return db.scalars(select(model).where(model.tenant_id == ledger_id).order_by(model.id)).all()

        return {
            "expenses": [{"id": row.id, "public_id": row.public_id, "amount": row.amount_cents,
                "merchant": row.merchant, "category": row.category, "tags": row.tags,
                "status": row.status, "row_version": row.row_version} for row in rows(Expense)],
            "tags": [{"id": row.public_id, "name": row.name, "row_version": row.row_version,
                "deleted": row.deleted_at is not None} for row in rows(Tag)],
            "tag_mutations": [{"id": row.mutation_public_id, "source": row.source_tag_public_id,
                "target": row.target_tag_public_id, "consumed": row.consumed_at is not None}
                for row in rows(TagMutationUndoGroup)],
            "catalog": [{"id": row.public_id, "name": row.display_name, "status": row.status,
                "target": row.merged_into_public_id, "row_version": row.row_version,
                "deleted": row.deleted_at is not None} for row in rows(MerchantCatalog)],
            "aliases": [{"id": row.public_id, "canonical": row.canonical_merchant, "alias": row.alias,
                "enabled": row.enabled, "row_version": row.row_version,
                "deleted": row.deleted_at is not None} for row in rows(MerchantAlias)],
            "categories": [{"id": row.public_id, "name": row.name, "deleted": row.deleted_at is not None}
                for row in rows(CategoryPreference)],
            "rules": [{"id": row.id, "keyword": row.keyword, "category": row.category,
                "priority": row.priority, "row_version": row.row_version,
                "deleted": row.deleted_at is not None} for row in rows(CategoryRule)],
            "applications": [{"id": row.public_id, "status": row.status, "changed": row.changed_count}
                for row in rows(RuleApplicationBatch)],
            "rule_changes": [{"expense_id": row.expense_id, "before": row.before_category,
                "after": row.after_category, "status": row.status} for row in rows(RuleApplicationChange)],
            "views": [{"id": row.public_id, "name": row.name, "tag_id": row.tag_public_id}
                for row in rows(SavedView)],
        }
