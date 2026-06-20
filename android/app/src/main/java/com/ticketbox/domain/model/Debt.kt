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
    /**
     * ADR-0049 §7.0 / 8e-6e external-debt repayment-rhythm classification (see [DebtKinds]). The
     * server's authoritative at-rest value; the detail-screen type chip lets the owner correct it
     * (`POST /api/debts/{id}/kind`). Defaults to [DebtKinds.UNSPECIFIED] so construction sites that
     * don't care need not name it; the mapper carries the server value through. Meaningful only for
     * external Debt (member debt is not classified) — it gates the backend payoff projection.
     */
    val debtKind: String = DebtKinds.UNSPECIFIED,
    /**
     * §B 完整 installment 合约排期。[installmentCount]（期数）/ [installmentPeriodMonths]（周期月数）是
     * at-rest 排期，仅 installment 外部债非空；[installmentPayoffDate]（ISO 日期串）与 [installmentPaidCount]
     * 是后端 DERIVED 只读派生（建账+期数×周期 的合约还清日 / floor(已还÷每期) 的已还期数），客户端纯读、绝不
     * 重算。全部默认 `null`（非 installment 或旧 payload）；只在 [isInstallmentScheduled] 为真时有意义。
     */
    val installmentCount: Long? = null,
    val installmentPeriodMonths: Long? = null,
    val installmentPayoffDate: String? = null,
    val installmentPaidCount: Long? = null,
    val homeCurrencyCode: String,
    val originalCurrencyCode: String?,
    val originalAmountMinor: Long?,
    val createdAt: String,
    val updatedAt: String,
    val rowVersion: Long,
    /**
     * The SERVER-authoritative debtor/creditor role for the viewer of a member Debt (§3.2): `true` =
     * viewer is the debtor (may propose / withdraw), `false` = creditor (may confirm / reject),
     * `null` = external Debt / not a party / a path without participant context (fact routes).
     *
     * The client must NOT derive this: it does not know its own account id, and ledger membership
     * does not distinguish a member Debt's same-ledger owner from a same-ledger member counterparty
     * (the backend grants both a full, ledger-id-present response). Both the detail fetch
     * (`GET /api/debts/{id}` → `get_participant_debt_response`) and the LIST (`GET /api/debts`, which
     * computes it per row for the authenticated viewer — slice 1A communal rows) populate it server-
     * side. Defaults to `null` (unknown) so non-member-debt construction sites need not name it; the
     * one real mapper ([com.ticketbox.data.repository.toDomain]) always carries the server value through.
     */
    val viewerIsDebtor: Boolean? = null,
    /**
     * Whether this cleared Debt was forgiven by the creditor ("算了，不用还了", ADR-0049 §3.7 / §4)
     * rather than fully repaid. SERVER-authoritative (= status cleared AND a DebtForgiveness fact);
     * the client never derives it. Drives the "被请客/请客" headline ([com.ticketbox.ui.screens]
     * `memberDebtHeadlineRes`) and the §5.6 celebration fork. Defaults to `false` (non-forgiven) so
     * construction sites that don't care need not name it; the mapper carries the server value through.
     */
    val isForgiven: Boolean = false,
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

    /**
     * §B 完整 installment：这笔债是否是「分期 + 已有排期」——即 [debtKind] 为 installment 且 [installmentCount]
     * 非空。后端只在该条件成立时才派生 [installmentPayoffDate] / [installmentPaidCount]，故详情屏据此 gate 分期
     * 计划卡的渲染。注意：完成措辞（已还清）必须 gate 在 [isCleared]，绝不用「已还期数==总期数」——提额调整会让
     * 已还期数达到 N/N 而剩余仍 > 0（后端 installment_paid_count docstring）。
     */
    val isInstallmentScheduled: Boolean
        get() = debtKind == DebtKinds.INSTALLMENT && installmentCount != null
}
