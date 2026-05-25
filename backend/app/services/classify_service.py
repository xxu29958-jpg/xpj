"""Backward-compatibility shim for the classification service.

The original ``classify_service`` was split into two focused modules:

* :mod:`app.services.rule_service` — rule CRUD + single-expense classification
* :mod:`app.services.rule_application_service` — batch application, preview,
  audit, and rollback over pending/confirmed expenses.

This shim re-exports the public surface so existing callers keep working
without any import changes. New code should import from the focused modules.
"""

from __future__ import annotations

from app.services.rule_application_service import (  # noqa: F401
    DEFAULT_RULE_APPLICATION_SCAN_LIMIT,
    apply_rules_to_confirmed,
    apply_rules_to_pending,
    list_rule_applications,
    preview_apply_rules_to_confirmed,
    preview_apply_rules_to_pending,
    preview_rule_for_pending,
    rollback_rule_application,
    validate_rule_application_preview,
)
from app.services.rule_service import (  # noqa: F401
    DEFAULT_RULES,
    classify_expense,
    create_rule,
    delete_rule,
    find_rule_for_tenant,
    get_rule_for_tenant,
    list_rules,
    seed_default_rules,
    update_rule,
)
