"""Keep a file's publication transaction separate from orphan disposal."""

from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _key(reference: str) -> int:
    value = b"ticketbox/attachment-publication/v1/" + reference.replace("\\", "/").encode()
    return int.from_bytes(sha256(value).digest()[:8], "big", signed=True)


def retain_publication(db: Session, reference: str) -> None:
    """Hold before creating bytes until their reference commits or rolls back."""
    with db.no_autoflush:
        db.execute(select(func.pg_advisory_xact_lock_shared(_key(reference))))


def try_claim_orphan(db: Session, reference: str) -> bool:
    """Never wait behind a publisher that may still need identity or row locks.

    Disposal must re-read references after this succeeds. A busy file remains
    untouched and can be inspected or retried after publication finishes.
    """
    with db.no_autoflush:
        return bool(db.scalar(select(func.pg_try_advisory_xact_lock(_key(reference)))))
