package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update

/** Publish one correction command outcome into the fact-page consumers. */
internal fun ExpenseFactViewModel.publishCorrectionOutcome(
    outcome: ExpenseCorrectionOutcome,
    draft: ExpenseCorrectionDraft,
    invalidatesAdvice: Boolean,
) {
    when (outcome) {
        is ExpenseCorrectionOutcome.Synced -> {
            _uiState.update {
                it.copy(
                    expense = outcome.expense,
                    correction = CorrectionFormState(),
                    message = UiText.res(
                        if (outcome.refreshPending) {
                            R.string.expense_correction_saved_refresh_pending
                        } else {
                            R.string.expense_correction_saved
                        },
                    ),
                    messageTone = if (outcome.refreshPending) {
                        MessageTone.Info
                    } else {
                        MessageTone.Success
                    },
                    doneAdviceInputsChanged = it.doneAdviceInputsChanged || invalidatesAdvice,
                )
            }
            // All fact consumers re-read server truth; no local revision publication.
            loadExpenseItems()
            loadExpenseSplits()
            loadExpenseRevisions()
        }
        is ExpenseCorrectionOutcome.Queued -> {
            _uiState.update {
                it.copy(
                    expense = outcome.expense,
                    expenseItems = projectQueuedAmountIntoItems(
                        current = it.expenseItems,
                        projectedAmountCents = outcome.expense.amountCents,
                        itemsChanged = draft.items != null,
                    ),
                    expenseSplits = projectQueuedAmountIntoSplits(
                        current = it.expenseSplits,
                        projectedAmountCents = outcome.expense.amountCents,
                        splitsChanged = draft.splits != null,
                    ),
                    correction = CorrectionFormState(),
                    message = UiText.res(R.string.expense_correction_queued),
                    messageTone = MessageTone.Info,
                    doneAdviceInputsChanged = it.doneAdviceInputsChanged || invalidatesAdvice,
                )
            }
        }
    }
}

private fun projectQueuedAmountIntoItems(
    current: ExpenseItems?,
    projectedAmountCents: Long?,
    itemsChanged: Boolean,
): ExpenseItems? {
    if (current == null || itemsChanged || current.parentAmountCents == projectedAmountCents) {
        return current
    }
    val projectedMismatch = if (projectedAmountCents == null) {
        null
    } else {
        current.itemsTotalAmountCents?.let { total ->
            // 与 current backend response 保持同一 parent − total 语义。
            runCatching { Math.subtractExact(projectedAmountCents, total) }.getOrNull()
        }
    }
    val projectedStatus = when {
        current.items.isEmpty() -> ItemsSumStatus.NO_ITEMS
        projectedMismatch == null || projectedMismatch == 0L -> ItemsSumStatus.MATCHED
        current.itemsSumStatus == ItemsSumStatus.MISMATCH_ACKNOWLEDGED -> ItemsSumStatus.MISMATCH_ACKNOWLEDGED
        else -> ItemsSumStatus.MISMATCH_KNOWN
    }
    return current.copy(
        parentAmountCents = projectedAmountCents,
        mismatchCents = projectedMismatch,
        itemsSumStatus = projectedStatus,
    )
}

private fun projectQueuedAmountIntoSplits(
    current: ExpenseSplits?,
    projectedAmountCents: Long?,
    splitsChanged: Boolean,
): ExpenseSplits? {
    if (current == null || splitsChanged || current.parentAmountCents == projectedAmountCents) {
        return current
    }
    val projectedMismatch = if (projectedAmountCents == null) {
        null
    } else {
        current.splitsTotalAmountCents?.let { total ->
            runCatching { Math.subtractExact(projectedAmountCents, total) }.getOrNull()
        }
    }
    return current.copy(
        parentAmountCents = projectedAmountCents,
        mismatchCents = projectedMismatch,
    )
}
