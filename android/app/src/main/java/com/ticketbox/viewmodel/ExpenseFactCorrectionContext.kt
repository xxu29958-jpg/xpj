package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update

/** Parent versions belong to the fact owner; a Loaded collection is not necessarily its current cohort. */
internal fun Expense?.matchesFactVersion(id: Long?, version: Long?): Boolean =
    this != null && rowVersion > 0 && this.id == id && rowVersion == version

internal val ExpenseFactUiState.currentCorrectionItems: ExpenseItems?
    get() = expenseItems?.takeIf {
        itemsLoadState == ExpenseDetailDataLoadState.Loaded && expense.matchesFactVersion(it.expenseId, it.parentRowVersion)
    }

internal val ExpenseFactUiState.currentCorrectionSplits: ExpenseSplits?
    get() = expenseSplits?.takeIf {
        splitsLoadState == ExpenseDetailDataLoadState.Loaded && expense.matchesFactVersion(it.expenseId, it.parentRowVersion)
    }

internal fun ExpenseFactViewModel.correctionContextError(): UiText? {
    val state = _uiState.value
    if (!state.correction.open) return null
    return when {
        state.readOnly -> UiText.res(R.string.expense_correction_readonly_blocked)
        !state.canStartCorrection || correctionBinding != state.correctionAccess?.binding ||
            !correctionBaseline.matchesFactVersion(state.expense?.id, state.expense?.rowVersion) ->
            UiText.res(R.string.expense_correction_snapshot_changed)
        else -> null
    }
}

internal fun ExpenseFactViewModel.canEditCorrectionItems(): Boolean =
    _uiState.value.correction.open && correctionContextError() == null && _uiState.value.currentCorrectionItems != null

internal fun ExpenseFactViewModel.canEditCorrectionSplits(): Boolean =
    _uiState.value.correction.open && correctionContextError() == null && _uiState.value.currentCorrectionSplits != null

/** Check again at publication; never refresh the frozen baseline or borrow a newer OCC for a draft. */
internal fun ExpenseFactViewModel.requireCurrentCorrectionContext(): Boolean {
    if (!_uiState.value.correction.open) return false
    val error = correctionContextError() ?: return true
    _uiState.update { it.copy(correction = it.correction.copy(submitError = error, saving = false)) }
    return false
}
