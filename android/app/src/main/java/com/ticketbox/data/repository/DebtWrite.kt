package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.Debt

internal val DEBT_WRITE_TYPES = setOf(PendingMutationType.RecordDebtAdjustment, PendingMutationType.RecordDebtRepayment)

@JsonClass(generateAdapter = true)
data class DebtWriteSubject(val publicId: String, val label: String?, val homeCurrencyCode: String)

/** The two existing direct Debt commands share recovery, never their financial meaning. */
sealed interface DebtWriteIntent {
    val subject: DebtWriteSubject
    val amountCents: Long
    val expectedRowVersion: Long
}

data class PendingDebtWrite(val row: OutboxRow, val intent: DebtWriteIntent?) {
    val adjustment: DebtAdjustmentPayload? get() = intent as? DebtAdjustmentPayload
    val repayment: DebtRepaymentPayload? get() = intent as? DebtRepaymentPayload
    val isTerminal: Boolean get() = row.status == PendingMutationStatus.Done || row.status == PendingMutationStatus.Abandoned
    val isUnresolved: Boolean get() = row.status in setOf(PendingMutationStatus.Pending,
        PendingMutationStatus.InFlight, PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
    val hasSupportedIntent: Boolean get() = intent != null
    val reductionRejected: Boolean
        get() = row.status == PendingMutationStatus.Failed && row.lastError == DEBT_ADJUSTMENT_NEGATIVE_REMAINING
    val canRetry: Boolean
        get() = row.status == PendingMutationStatus.Failed && hasSupportedIntent && !reductionRejected &&
            row.lastError?.startsWith("outbox_row_expired") != true
}

internal fun debtWriteTarget(publicId: String): String = "debt:$publicId"

/** Actual bound Room state, with terminal arrivals used only to invalidate canonical queries. */
data class DebtWriteObservation(
    val binding: LogicalSessionBinding?,
    val writes: List<PendingDebtWrite>,
    val initial: Boolean,
    val newlyTerminal: List<PendingDebtWrite>,
) {
    val requiresRefresh: Boolean get() = initial || newlyTerminal.isNotEmpty()
    val unresolvedTargetIds: Set<String> get() = writes.filter { it.isUnresolved }.mapTo(mutableSetOf()) { it.row.targetId }

    /** Call only for a canonical query started after this observation; this does not prove freshness. */
    fun acceptsCanonical(debt: Debt): Boolean = writes.filter { it.row.targetId == debtWriteTarget(debt.publicId) }
        .all { pending ->
            when (pending.row.status) {
                PendingMutationStatus.Done -> debt.rowVersion > (pending.row.expectedRowVersion ?: Long.MAX_VALUE)
                PendingMutationStatus.Abandoned -> pending.row.expectedRowVersion?.let { debt.rowVersion >= it } ?: true
                else -> !pending.isUnresolved
            }
        }
}
