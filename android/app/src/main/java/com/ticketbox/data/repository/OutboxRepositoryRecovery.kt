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

internal suspend fun PendingMutationDao.deleteResolvedBeforeCutoff(cutoffIso: String): Int =
    deleteResolvedBefore(
        doneStatus = PendingMutationStatus.Done.wireValue,
        cutoffIso = cutoffIso,
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
        listOf(PendingMutationType.UndoExpense.wireValue, PendingMutationType.RejectExpense.wireValue, PendingMutationType.ConfirmExpense.wireValue,
            PendingMutationType.SplitAgreement.wireValue, PendingMutationType.ReplaceItems.wireValue,
            PendingMutationType.ReplaceSplits.wireValue, PendingMutationType.AcknowledgeItemsMismatch.wireValue),
        listOf(status.wireValue),
    ).first().firstOrNull { it.id == id } ?: return false
    return (original.type == PendingMutationType.SplitAgreement.wireValue &&
        (freshToken != null || original.lastError in SPLIT_SHARE_REFUSALS)) ||
        original.lastError in EXPENSE_ORIGINAL_REVIEW_ERRORS ||
        (original.type == PendingMutationType.UndoExpense.wireValue &&
            (freshToken != null || original.lastError == "expense_not_found"))
}
