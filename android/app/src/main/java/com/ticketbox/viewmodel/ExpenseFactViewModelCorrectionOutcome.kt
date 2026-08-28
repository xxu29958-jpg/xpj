package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update

/** Publish one correction command outcome into the fact-page consumers. */
internal fun ExpenseFactViewModel.publishCorrectionOutcome(
    outcome: ExpenseCorrectionOutcome,
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
                    correction = CorrectionFormState(),
                    message = UiText.res(R.string.expense_correction_queued),
                    messageTone = MessageTone.Info,
                    doneAdviceInputsChanged = it.doneAdviceInputsChanged || invalidatesAdvice,
                )
            }
        }
    }
}
