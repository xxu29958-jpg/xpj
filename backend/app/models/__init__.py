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
    BudgetAdvisorAuditLog,
    BudgetAdvisorQuotaLock,
)
from app.models.app_meta import AppMeta
from app.models.auth import (
    Invitation,
    PairingAttemptFailure,
    PairingCode,
    UploadLink,
    UploadLinkDailyUsage,
    UploadLinkRemoteAttempt,
)
from app.models.background_task import BackgroundTask
from app.models.bill_split import BillSplitInvitation
from app.models.budget import (
    Budget,
    BudgetCategory,
    DashboardCardPreference,
    DebtGoalLink,
    Goal,
)
from app.models.catalog import (
    CategoryPreference,
    DuplicateIgnore,
    ExpenseTag,
    MerchantAlias,
    MerchantCatalog,
    Tag,
    TagMutationUndoGroup,
    TagMutationUndoItem,
)
from app.models.classification import (
    CategoryRule,
    RuleApplicationBatch,
    RuleApplicationChange,
)
from app.models.debt import (
    Debt,
    DebtAdjustment,
    DebtForgiveness,
    DebtVoid,
    MemberRepaymentProposal,
    Repayment,
    RepaymentDraft,
    RepaymentVoid,
)
from app.models.exchange import ExchangeRate, FxRate
from app.models.expense import Expense, ExpenseItem, ExpenseSplit
from app.models.financial_planning import MonthlyIncomePlan
from app.models.idempotency import ApiIdempotencyKey
from app.models.identity import (
    Account,
    AuthToken,
    Device,
    Ledger,
    LedgerAuditLog,
    LedgerMember,
)
from app.models.import_csv import CsvImportBatch, CsvImportRow
from app.models.learning import AlgorithmDecision, LedgerLearningEvent
from app.models.ocr_facts import OcrFact
from app.models.recurring import RecurringItem
from app.models.system import (
    BootstrapSecretConsumption,
    SchedulerLease,
    SchemaMigration,
    UserUiPreference,
)

__all__ = [
    "Account",
    "AiMemberAnonMap",
    "AiMerchantAnonMap",
    "AiTransactionTempIdMap",
    "AlgorithmDecision",
    "ApiIdempotencyKey",
    "AppMeta",
    "AuthToken",
    "BackgroundTask",
    "BillSplitInvitation",
    "BootstrapSecretConsumption",
    "Budget",
    "BudgetAdvisorAuditLog",
    "BudgetAdvisorQuotaLock",
    "BudgetCategory",
    "CategoryPreference",
    "CategoryRule",
    "CsvImportBatch",
    "CsvImportRow",
    "DashboardCardPreference",
    "Debt",
    "DebtAdjustment",
    "DebtForgiveness",
    "DebtGoalLink",
    "DebtVoid",
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
    "LedgerLearningEvent",
    "LedgerMember",
    "MemberRepaymentProposal",
    "MerchantAlias",
    "MerchantCatalog",
    "MonthlyIncomePlan",
    "OcrFact",
    "PairingAttemptFailure",
    "PairingCode",
    "RecurringItem",
    "Repayment",
    "RepaymentDraft",
    "RepaymentVoid",
    "RuleApplicationBatch",
    "RuleApplicationChange",
    "SchedulerLease",
    "SchemaMigration",
    "Tag",
    "TagMutationUndoGroup",
    "TagMutationUndoItem",
    "UploadLink",
    "UploadLinkDailyUsage",
    "UploadLinkRemoteAttempt",
    "UserUiPreference",
]
