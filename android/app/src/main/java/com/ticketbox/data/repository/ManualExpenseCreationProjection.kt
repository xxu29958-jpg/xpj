package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto

/** A read projection of the existing original row; it never creates or changes an intent. */
data class ManualExpenseCreationProjection(
    val row: OutboxRow,
    val request: ExpenseManualCreateRequestDto?,
    val acceptedExpenseId: Long? = null,
)

/** Acceptance belongs to the same Outbox row; read-cache identity is disposable. */
@JsonClass(generateAdapter = true)
internal data class ManualExpenseCreationReceipt(val expenseId: Long)

private val manualCreationReceiptAdapter by lazy {
    Moshi.Builder().build().adapter(ManualExpenseCreationReceipt::class.java)
}

internal fun manualCreationReceiptJson(expenseId: Long): String =
    manualCreationReceiptAdapter.toJson(ManualExpenseCreationReceipt(expenseId))

internal suspend fun ExpenseRepositoryCore.describeManualCreation(row: OutboxRow): ManualExpenseCreationProjection? {
    if (row.type != PendingMutationType.CreateExpense) return null
    val request = runCatching { offlineMutations.manualCreateAdapter.fromJson(row.payloadJson) }.getOrNull()
    val id = row.receiptJson?.takeIf { row.status == PendingMutationStatus.Done }?.let { json ->
        runCatching { manualCreationReceiptAdapter.fromJson(json)?.expenseId?.takeIf { it > 0 } }.getOrNull()
    }
    return ManualExpenseCreationProjection(row, request, id)
}

internal suspend fun ExpenseRepositoryCore.stopManualCreation(row: OutboxRow): Result<Unit> = errorHandler.safeCall {
    val bound = ledgerRequestGuard.bind()
    bound.requireStillActiveFor(requireNotNull(row.bindingOrNull()))
    val ref = parseExpenseTargetRef(row.targetId)?.takeIf { it.startsWith("local:") }?.removePrefix("local:")
    val stopped = offlineMutations.outbox.discardOriginalExpense(bound, row) {
        // This callback runs in the same Room transaction as the status-checked queue removal.
        val local = if (ref.isNullOrBlank()) null else expenseDao.getConfirmed(bound.ledgerId)
            .singleOrNull { it.clientRef == ref && it.serverId == null }
        if (local != null) expenseDao.deleteByLocalId(local.id)
    }
    if (!stopped) throw RepositoryException("原提交状态已变化，请重新查看。")
}
