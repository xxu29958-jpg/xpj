"""Owner Console view-model helpers.

Aggregates data needed by the Owner Console HTML pages. These functions are
called exclusively from :mod:`app.routes.owner_console` (plus
``owner_ledgers`` and ``web_common``) and must never depend on FastAPI
Request or return HTTP responses.

The package internally splits along the same domain seams the Owner Console UI
shows:

- ``_common``         — module-wide helpers (logger, timezone, amount
                        formatting, owner account lookups)
- ``_ledger_console`` — ledger discovery + management VMs
- ``_recurring_ops``  — recurring summary VM consumed by the index card
- ``_recycle_bin``    — unified archived/deleted restore surface
- ``_devices``        — device CRUD wrappers scoped to managed ledgers
- ``_upload_links``   — upload-link CRUD wrappers + public URL composer
- ``_pairing``        — pairing code creation
- ``_rule_audit``     — rule-application audit listing
- ``_index``          — composes the dashboard VM from all of the above
                        (the four-card pattern with broad-except
                        per-card degradation — see S-006)

Dependency rule: domain submodules import from ``_common`` (and
``_ledger_console`` if they need the managed-ledger lookup). They do not
import each other. Only ``_index`` and ``_rule_audit`` import other
domain modules. ``_common`` and ``_ledger_console`` have no
intra-package imports.
"""

from __future__ import annotations

from app.services.owner_console_service._common import (
    OWNER_CONSOLE_TIMEZONE,
    get_owner_account_id,
)
from app.services.owner_console_service._devices import (
    DeviceSummary,
    do_delete_device,
    do_rename_device,
    do_revoke_device,
    get_devices,
)
from app.services.owner_console_service._fx import (
    FxPanelVM,
    FxRowVM,
    get_fx_panel_vm,
)
from app.services.owner_console_service._index import (
    BudgetStatusVM,
    ConsoleIndexVM,
    get_index_vm,
)
from app.services.owner_console_service._ledger_console import (
    LedgerConsoleVM,
    LedgerHealthVM,
    do_archive_ledger,
    do_create_ledger,
    do_unarchive_ledger,
    get_default_ledger_id,
    list_archived_console_ledgers,
    list_console_ledger_choices,
    list_console_ledgers,
    list_ledger_health,
    list_manageable_console_ledgers,
)
from app.services.owner_console_service._pairing import (
    PairingCodeResult,
    do_create_pairing_code,
)
from app.services.owner_console_service._recurring_ops import (
    RecurringOpsVM,
    get_recurring_ops,
)
from app.services.owner_console_service._recycle_bin import (
    RecycleBinItemVM,
    RecycleBinVM,
    get_recycle_bin_vm,
    restore_recycle_bin_item,
)
from app.services.owner_console_service._rule_audit import (
    RuleApplicationAuditRow,
    RuleApplicationAuditVM,
    get_rule_application_audit,
)
from app.services.owner_console_service._upload_links import (
    UploadLinkSecret,
    UploadLinkSummary,
    compose_public_upload_url,
    do_create_upload_link,
    do_delete_upload_link,
    do_extend_upload_link,
    do_revoke_upload_link,
    do_rotate_upload_link,
    do_update_upload_link_limits,
    get_upload_links,
)

__all__ = [
    "BudgetStatusVM",
    "ConsoleIndexVM",
    "DeviceSummary",
    "FxPanelVM",
    "FxRowVM",
    "LedgerConsoleVM",
    "LedgerHealthVM",
    "OWNER_CONSOLE_TIMEZONE",
    "PairingCodeResult",
    "RecurringOpsVM",
    "RecycleBinItemVM",
    "RecycleBinVM",
    "RuleApplicationAuditRow",
    "RuleApplicationAuditVM",
    "UploadLinkSecret",
    "UploadLinkSummary",
    "compose_public_upload_url",
    "do_archive_ledger",
    "do_create_ledger",
    "do_create_pairing_code",
    "do_create_upload_link",
    "do_delete_device",
    "do_delete_upload_link",
    "do_extend_upload_link",
    "do_rename_device",
    "do_revoke_device",
    "do_revoke_upload_link",
    "do_rotate_upload_link",
    "do_unarchive_ledger",
    "do_update_upload_link_limits",
    "get_default_ledger_id",
    "get_devices",
    "get_fx_panel_vm",
    "get_index_vm",
    "get_owner_account_id",
    "get_recurring_ops",
    "get_recycle_bin_vm",
    "get_rule_application_audit",
    "get_upload_links",
    "list_archived_console_ledgers",
    "list_console_ledger_choices",
    "list_console_ledgers",
    "list_ledger_health",
    "list_manageable_console_ledgers",
    "restore_recycle_bin_item",
]
