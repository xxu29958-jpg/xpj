package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.flow.first

/**
 * Recovery-side Room checks for [OutboxRepository].
 * The repository holds the binding lease and only hands over a resolved binding.
 */

internal suspend fun PendingMutationDao.expireBoundIfOverAge(
    id: Long,
    binding: OutboxBinding,
    fromStatus: String,
    cutoffIso: String,
): Boolean = expireBoundRowIfStatusAndOverAge(
    id = id,
    ownerKey = binding.ownerStorageKey,
    ledgerId = binding.ledgerId,
    fromStatus = fromStatus,
    cutoffCreatedAtIso = cutoffIso,
) > 0

private val expenseRecoveryCheckedTypes = listOf(
    PendingMutationType.UndoExpense.wireValue,
    PendingMutationType.RejectExpense.wireValue,
    PendingMutationType.ConfirmExpense.wireValue,
    PendingMutationType.SplitAgreement.wireValue,
    PendingMutationType.ReplaceItems.wireValue,
    PendingMutationType.ReplaceSplits.wireValue,
    PendingMutationType.AcknowledgeItemsMismatch.wireValue,
    PendingMutationType.VoidExpenseOffset.wireValue,
)

private val freshTokenForbiddenExpenseTypes = setOf(
    PendingMutationType.VoidExpenseOffset.wireValue,
    PendingMutationType.SplitAgreement.wireValue,
    PendingMutationType.UndoExpense.wireValue,
)

internal suspend fun PendingMutationDao.refusesExpenseRecovery(
    binding: OutboxBinding,
    id: Long,
    status: PendingMutationStatus,
    freshToken: Long?,
): Boolean {
    val original = observeActiveByTypes(
        binding.ownerStorageKey,
        binding.ledgerId,
        expenseRecoveryCheckedTypes,
        listOf(status.wireValue),
    ).first().firstOrNull { it.id == id } ?: return false
    if (freshToken != null && original.type in freshTokenForbiddenExpenseTypes) return true
    if (freshToken != null && original.type == PendingMutationType.ConfirmExpense.wireValue &&
        runCatching { original.toDomain().confirmationFunding().isNotEmpty() }.getOrDefault(true)
    ) return true
    return original.lastError in EXPENSE_ORIGINAL_REVIEW_ERRORS ||
        (original.type == PendingMutationType.SplitAgreement.wireValue && original.lastError in SPLIT_SHARE_REFUSALS) ||
        (original.type == PendingMutationType.UndoExpense.wireValue && original.lastError == "expense_not_found")
}

internal suspend fun PendingMutationDao.retryEligibleUploadRows(
    binding: OutboxBinding,
    eligible: List<OutboxRow>,
    overAgeCutoffIso: () -> String,
): Pair<Boolean, Int> {
    var expired = false
    var retried = 0
    for (row in eligible) {
        if (expireBoundIfOverAge(row.id, binding, PendingMutationStatus.Failed.wireValue, overAgeCutoffIso())) {
            expired = true
        } else {
            retried += retryFailed(row.id, binding.ownerStorageKey, binding.ledgerId, NON_RETRYABLE_UPLOAD_ERRORS)
        }
    }
    return (expired || retried > 0) to retried
}
