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
    /**
     * The SERVER-authoritative debtor/creditor role for the viewer of a member Debt (§3.2): `true` =
     * viewer is the debtor (may propose / withdraw), `false` = creditor (may confirm / reject),
     * `null` = external Debt / not a party / a path without participant context (list & fact routes).
     *
     * The client must NOT derive this: it does not know its own account id, and ledger membership
     * does not distinguish a member Debt's same-ledger owner from a same-ledger member counterparty
     * (the backend grants both a full, ledger-id-present response). The detail fetch
     * (`GET /api/debts/{id}` → `get_participant_debt_response`) is the only path that populates it.
     * Defaults to `null` (unknown) so non-member-debt construction sites need not name it; the one
     * real mapper ([com.ticketbox.data.repository.toDomain]) always carries the server value through.
     */
    val viewerIsDebtor: Boolean? = null,
) {
    val isOpen: Boolean get() = status == DebtLinkStatuses.OPEN
    val isCleared: Boolean get() = status == DebtLinkStatuses.CLEARED
    val isVoided: Boolean get() = status == DebtLinkStatuses.VOIDED
    val isExternal: Boolean get() = counterpartyType == DebtCounterpartyTypes.EXTERNAL
    val isMember: Boolean get() = counterpartyType == DebtCounterpartyTypes.MEMBER
    val isBillSplit: Boolean get() = sourceType == DebtSourceTypes.BILL_SPLIT

    /**
     * Whether direct fact writes (repayment / adjustment / void, ADR-0049 §3) are accepted on this
     * Debt. Mirrors the backend `guard_direct_fact_writable` (external + manual only); member /
     * bill_split obligations route through the affected-party proposal flow (§5.2, slice 8d), so the
     * detail screen hides the direct-write actions for them rather than showing a button that 409s.
     */
    val isDirectWritable: Boolean get() = isExternal && sourceType == DebtSourceTypes.MANUAL

    /** The complement of [viewerIsDebtor] for a member Debt (may confirm / reject, §3.2); null when role is unknown. */
    val viewerIsCreditor: Boolean? get() = viewerIsDebtor?.let { !it }
}
