"""Compatibility facade for the debt-repayment goal service.

Keep importing public debt-goal operations from this module. Implementation is
split by responsibility so each service module remains reviewable.
"""

from app.services.goal_debt_repayment_commands import (
    acknowledge_integrity_review,
    replace_debt_repayment_goal_links,
    set_debt_goal_target_date,
)
from app.services.goal_debt_repayment_core import (
    GOAL_TYPE,
    build_debt_repayment_goal_response,
    create_debt_repayment_goal,
    create_debt_repayment_goal_idempotently,
    ledger_has_goal_needing_review,
    list_debt_repayment_goals,
)
from app.services.goal_debt_repayment_idempotency import (
    acknowledge_integrity_review_idempotently,
    archive_debt_repayment_goal_idempotently,
    remove_voided_debt_goal_links_idempotently,
    replace_debt_repayment_goal_links_idempotently,
    restore_debt_repayment_goal_idempotently,
    set_debt_goal_target_date_idempotently,
)

__all__ = [
    "GOAL_TYPE",
    "acknowledge_integrity_review",
    "acknowledge_integrity_review_idempotently",
    "archive_debt_repayment_goal_idempotently",
    "build_debt_repayment_goal_response",
    "create_debt_repayment_goal",
    "create_debt_repayment_goal_idempotently",
    "ledger_has_goal_needing_review",
    "list_debt_repayment_goals",
    "remove_voided_debt_goal_links_idempotently",
    "replace_debt_repayment_goal_links",
    "replace_debt_repayment_goal_links_idempotently",
    "restore_debt_repayment_goal_idempotently",
    "set_debt_goal_target_date",
    "set_debt_goal_target_date_idempotently",
]
