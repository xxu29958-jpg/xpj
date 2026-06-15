package com.ticketbox.domain.model

/**
 * ADR-0049 §2 (slice 8) Debt entity domain model.
 *
 * Reuses the canonical value objects from [DebtGoal] ([DebtDirections],
 * [DebtCounterpartyTypes], [DebtLinkStatuses]) so branching/coloring never hardcodes the raw
 * backend strings. `remaining`/`paid`/`status` are server-derived from the append-only fact
 * fold; the client never recomputes them. [ledgerId] is nullable (redacted for a cross-ledger
 * participant view, §5.2) — use [publicId] as the local key, never `ledgerId`.
 */
object DebtSourceTypes {
    const val MANUAL = "manual"
    const val BILL_SPLIT = "bill_split"
}

data class Debt(
    val publicId: String,
    val ledgerId: String?,
    val direction: String,
    val counterpartyType: String,
    val counterpartyAccountId: Long?,
    val counterpartyLabel: String?,
    val principalAmountCents: Long,
    val remainingAmountCents: Long,
    val paidAmountCents: Long,
    val status: String,
    val sourceType: String,
    val sourceId: String?,
    val homeCurrencyCode: String,
    val originalCurrencyCode: String?,
    val originalAmountMinor: Long?,
    val createdAt: String,
    val updatedAt: String,
    val rowVersion: Long,
) {
    val isOpen: Boolean get() = status == DebtLinkStatuses.OPEN
    val isCleared: Boolean get() = status == DebtLinkStatuses.CLEARED
    val isVoided: Boolean get() = status == DebtLinkStatuses.VOIDED
    val isExternal: Boolean get() = counterpartyType == DebtCounterpartyTypes.EXTERNAL
    val isBillSplit: Boolean get() = sourceType == DebtSourceTypes.BILL_SPLIT

    /**
     * Whether direct fact writes (repayment / adjustment / void, ADR-0049 §3) are accepted on this
     * Debt. Mirrors the backend `guard_direct_fact_writable` (external + manual only); member /
     * bill_split obligations route through the affected-party proposal flow (§5.2, slice 8d), so the
     * detail screen hides the direct-write actions for them rather than showing a button that 409s.
     */
    val isDirectWritable: Boolean get() = isExternal && sourceType == DebtSourceTypes.MANUAL
}
