"""Fixed live PostgreSQL observation for installed runtime admission."""

from sqlalchemy import text

DATASET_AUTHORITY_QUERY = text(
    """
    SELECT dataset_id, client_generation, restore_epoch, schema_revision,
           schema_min_compatible, semantic_revision, restored_from_backup_id
    FROM public.dataset_authority
    WHERE singleton_id = 1
    """
)

__all__ = ["DATASET_AUTHORITY_QUERY"]
