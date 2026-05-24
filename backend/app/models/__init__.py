"""Domain-organized ORM models.

This package was split from a single ``models.py`` into one file per domain to
make navigation easier. All names previously importable from ``app.models``
remain importable at the same path (``from app.models import Expense``), so
no caller needs to change.
"""

from __future__ import annotations

from app.models.ai_advisor import (
    AiMemberAnonMap,
    AiMerchantAnonMap,
    AiTransactionTempIdMap,
)
from app.models.app_meta import AppMeta
from app.models.auth import Invitation, PairingCode, UploadLink
from app.models.background_task import BackgroundTask
from app.models.bill_split import BillSplitInvitation
from app.models.budget import Budget, BudgetCategory, DashboardCardPreference, Goal
from app.models.catalog import DuplicateIgnore, ExpenseTag, MerchantAlias, Tag
from app.models.classification import (
    CategoryRule,
    RuleApplicationBatch,
    RuleApplicationChange,
)
from app.models.exchange import ExchangeRate, FxRate
from app.models.expense import Expense, ExpenseItem, ExpenseSplit
from app.models.financial_planning import MonthlyIncomePlan
from app.models.identity import (
    Account,
    AuthToken,
    Device,
    Ledger,
    LedgerAuditLog,
    LedgerMember,
)
from app.models.import_csv import CsvImportBatch, CsvImportRow
from app.models.recurring import RecurringItem
from app.models.system import BootstrapSecretConsumption, SchemaMigration, UserUiPreference

__all__ = [
    "Account",
    "AiMemberAnonMap",
    "AiMerchantAnonMap",
    "AiTransactionTempIdMap",
    "AppMeta",
    "AuthToken",
    "BackgroundTask",
    "BillSplitInvitation",
    "BootstrapSecretConsumption",
    "Budget",
    "BudgetCategory",
    "CategoryRule",
    "CsvImportBatch",
    "CsvImportRow",
    "DashboardCardPreference",
    "Device",
    "DuplicateIgnore",
    "Expense",
    "ExpenseItem",
    "ExpenseSplit",
    "ExpenseTag",
    "ExchangeRate",
    "FxRate",
    "Goal",
    "Invitation",
    "Ledger",
    "LedgerAuditLog",
    "LedgerMember",
    "MerchantAlias",
    "MonthlyIncomePlan",
    "PairingCode",
    "RecurringItem",
    "RuleApplicationBatch",
    "RuleApplicationChange",
    "SchemaMigration",
    "Tag",
    "UploadLink",
    "UserUiPreference",
]
