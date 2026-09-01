package com.ticketbox.domain.model

data class ExpenseOffsetDraft(
    val kind: StreamOffsetKind,
    val originalAmountMinor: Long?,
    val accountingDate: String,
    val reason: String,
)

enum class ExpenseOffsetStatus { Active, Voided }

data class ExpenseOffsetFact(
    val publicId: String,
    val kind: StreamOffsetKind,
    val status: ExpenseOffsetStatus,
    val originalCurrencyCode: String,
    val originalAmountMinor: Long,
    val homeCurrencyCode: String,
    val amountCents: Long,
    val streamAmountCents: Long,
    val accountingDate: String,
    val category: String,
    val reason: String,
    val rowVersion: Long,
    val factRevision: Long,
    val createdAt: String,
    val updatedAt: String,
)

data class ExpenseFinancialSummary(
    val grossOriginalMinor: Long,
    val grossHomeAmountCents: Long,
    val rootStreamAmountCents: Long,
    val activeRefundedOriginalMinor: Long,
    val remainingRefundableOriginalMinor: Long,
    val lineageHomeNetCents: Long,
    val fxDifferenceCents: Long,
    val status: ExpenseLineageStatus,
)

enum class ExpenseOffsetChangeKind { Created, Correction, Void }

data class ExpenseOffsetRevision(
    val publicId: String,
    val offsetPublicId: String,
    val revisionNumber: Long,
    val changeKind: ExpenseOffsetChangeKind,
    val reason: String,
    val actorAccountName: String?,
    val actorDeviceName: String?,
    val createdAt: String,
)

enum class ExpenseRelationshipReason { SourceRefunded, SourceChargeback, SourceReversed }

data class CancelledPendingInvitationImpact(
    val invitationPublicId: String,
    val reason: ExpenseRelationshipReason,
)

data class AcceptedInvitationImpact(
    val invitationPublicId: String,
    val reason: ExpenseRelationshipReason,
    val receiverDisplayName: String?,
    val debtPublicId: String?,
    val originalAgreedShareHomeMinor: Long,
    val suggestedNetShareHomeMinor: Long,
)

data class ExpenseRelationshipImpacts(
    val pendingInvitesCancelled: List<CancelledPendingInvitationImpact>,
    val acceptedImpacts: List<AcceptedInvitationImpact>,
)

data class ExpenseFactBundle(
    val root: Expense,
    val financialSummary: ExpenseFinancialSummary,
    val activeOffsets: List<ExpenseOffsetFact>,
    val recentHistory: List<ExpenseOffsetRevision>,
    val relationshipImpacts: ExpenseRelationshipImpacts,
)

enum class ExpenseOffsetIntentKind { Create, Void }

data class PendingExpenseOffsetIntent(
    val operation: ExpenseOffsetIntentKind,
    val offsetKind: StreamOffsetKind?,
    val offsetPublicId: String?,
    val reason: String,
)

sealed interface ExpenseOffsetMutationOutcome {
    data class Synced(
        val bundle: ExpenseFactBundle,
        val refreshPending: Boolean,
    ) : ExpenseOffsetMutationOutcome

    data class Queued(val intent: PendingExpenseOffsetIntent) : ExpenseOffsetMutationOutcome
}
