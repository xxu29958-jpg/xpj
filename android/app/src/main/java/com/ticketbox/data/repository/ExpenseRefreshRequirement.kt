package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.PendingMutationDao
import kotlinx.coroutines.flow.first

/** Preserve persisted receipts; this marker describes a missing projection, not a failed command. */
internal const val EXPENSE_REFRESH_PREFIX = "correction_refresh_required:"

internal val EXPENSE_REFRESH_TYPES = setOf(
    PendingMutationType.CorrectExpense,
    PendingMutationType.PatchExpense,
    PendingMutationType.ConfirmExpense,
    PendingMutationType.RejectExpense,
    PendingMutationType.MarkNotDuplicate,
    PendingMutationType.RetryOcr,
    PendingMutationType.RecognizeText,
    PendingMutationType.CreateExpenseOffset,
    PendingMutationType.VoidExpenseOffset,
)

internal fun expenseRefreshVersion(error: String?): Long? =
    error?.takeIf { it.startsWith(EXPENSE_REFRESH_PREFIX) }?.removePrefix(EXPENSE_REFRESH_PREFIX)?.toLongOrNull()

internal fun OutboxRow.requiresExpenseRefresh(): Boolean =
    status == PendingMutationStatus.Done && type in EXPENSE_REFRESH_TYPES && expenseRefreshVersion(lastError) != null

/** A promoted local original keeps its target; only its own accepted receipt supplies the server identity. */
internal fun expenseRefreshTargetId(targetId: String, receiptJson: String?): Long? {
    val ref = parseExpenseTargetRef(targetId) ?: return null
    if (ref.startsWith("local:") && ref.removePrefix("local:").isNotBlank()) {
        return expenseAcceptanceReceiptId(receiptJson)
    }
    return ref.toLongOrNull()?.takeIf { it > 0 }
}

/** Called inside admission: repair a missing projection before another fact command. */
internal fun requireExpenseRefreshComplete(rows: List<OutboxRow>) {
    if (rows.any { it.requiresExpenseRefresh() }) {
        throw RepositoryException("操作已完成，请先刷新账单再继续。")
    }
}

internal fun PendingMutationDao.observeExpenseRefreshRows(binding: OutboxBinding) =
    observeActiveByTypes(binding.ownerStorageKey, binding.ledgerId,
        EXPENSE_REFRESH_TYPES.map { it.wireValue }, listOf(PendingMutationStatus.Done.wireValue))

/** Admission already holds the binding lease; promoted originals must still block a new numeric-target write. */
internal suspend fun PendingMutationDao.expenseAdmissionRows(
    binding: OutboxBinding,
    targetId: String,
    targetRows: List<OutboxRow>,
): List<OutboxRow> {
    val expenseId = expenseRefreshTargetId(targetId, null) ?: return targetRows
    val refreshRows = observeExpenseRefreshRows(binding).first().map { it.toDomain() }.filter {
        it.requiresExpenseRefresh() && expenseRefreshTargetId(it.targetId, it.receiptJson) == expenseId
    }
    return (targetRows + refreshRows).distinctBy { it.id }
}

/** The repository holds its binding lease; compare-clear preserves the original command and delivery. */
internal suspend fun PendingMutationDao.clearAdoptedExpenseRefreshes(binding: OutboxBinding, versions: Map<Long, Long>) {
    for (row in observeExpenseRefreshRows(binding).first()) {
        val required = expenseRefreshVersion(row.lastError) ?: continue
        val target = expenseRefreshTargetId(row.targetId, row.receiptJson) ?: continue
        if ((versions[target] ?: continue) >= required) clearExpenseRefresh(row.id, requireNotNull(row.lastError))
    }
}
