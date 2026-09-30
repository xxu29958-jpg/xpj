package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal fun ExpenseFactViewModel.observeFactReadDenials() {
    viewModelScope.launch {
        repository.factReadAccessDenials.collect { denial ->
            if (_uiState.value.correctionAccess?.binding == denial.binding) retireDeniedFactReads(denial.failure)
        }
    }
}

/** Authorization loss retires displayed facts, never the separately retained original input. */
internal fun ExpenseFactViewModel.retireDeniedFactReads(error: Throwable): Boolean {
    if ((error as? RepositoryException)?.httpStatusCode !in setOf(401, 403, 404)) return false
    factInputLoadGeneration++
    factInputSession = null
    correctionBaseline = null
    correctionBinding = null
    correctionOriginalItems = null
    correctionOriginalSplits = null
    factBundleLoadGeneration++
    revisionLoadGeneration++
    expenseLoadGeneration++
    itemsLoadGeneration++
    splitsLoadGeneration++
    thumbnailLoadGeneration++
    fullImageLoadGeneration++
    _uiState.update {
        ExpenseFactUiState(correctionAccess = it.correctionAccess, readOnly = it.readOnly, factInputsReady = false,
            corrections = it.corrections, expenseRefreshRequirements = it.expenseRefreshRequirements,
            requiredRootRowVersion = it.requiredRootRowVersion, expenseLoading = false,
            expenseLoadState = ExpenseDetailDataLoadState.Failed,
            expenseLoadMessage = error.toUiText(R.string.expense_fact_offsets_failed))
    }
    return true
}
