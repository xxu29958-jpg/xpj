"""Rule application service: preview, apply, list, rollback.

Split into 4 phase-oriented sub-modules:

- ``_common``: shared SQL helpers, candidate scanning, audit token, internal
  ``_try_apply_rule_category`` / ``_try_rollback_rule_change`` (test-imported).
- ``_preview``: pure read previews + token validation.
- ``_apply``: mutating apply + RuleApplicationBatch / RuleApplicationChange
  audit writes.
- ``_history``: list + rollback past application batches.

External callers keep importing from ``app.services.rule_application_service``.
"""

from __future__ import annotations

from app.services.rule_application_service._apply import (
    apply_rules_to_confirmed,
    apply_rules_to_pending,
)
from app.services.rule_application_service._common import (
    DEFAULT_RULE_APPLICATION_SCAN_LIMIT,
    _try_apply_rule_category,
    _try_rollback_rule_change,
)
from app.services.rule_application_service._history import (
    list_rule_applications,
    rollback_rule_application,
)
from app.services.rule_application_service._preview import (
    preview_apply_rules_to_confirmed,
    preview_apply_rules_to_pending,
    preview_rule_for_pending,
    validate_rule_application_preview,
)

__all__ = [
    "DEFAULT_RULE_APPLICATION_SCAN_LIMIT",
    "_try_apply_rule_category",
    "_try_rollback_rule_change",
    "apply_rules_to_confirmed",
    "apply_rules_to_pending",
    "list_rule_applications",
    "preview_apply_rules_to_confirmed",
    "preview_apply_rules_to_pending",
    "preview_rule_for_pending",
    "rollback_rule_application",
    "validate_rule_application_preview",
]
