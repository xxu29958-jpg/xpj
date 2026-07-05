package com.ticketbox.ui.screens.budget

import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.BudgetUiState

internal enum class BudgetPageStatus {
    Loading,
    LoadFailed,
    NotEnabled,
    Active,
}

internal data class BudgetPageDecision(
    val status: BudgetPageStatus,
    val configuredBudget: BudgetMonthly?,
)

internal fun budgetPageDecision(state: BudgetUiState): BudgetPageDecision {
    val budget = state.budget?.takeIf { it.configured }
    return BudgetPageDecision(
        status = when {
            state.loading && state.budget == null -> BudgetPageStatus.Loading
            state.loadError != null && !state.loading -> BudgetPageStatus.LoadFailed
            budget == null -> BudgetPageStatus.NotEnabled
            else -> BudgetPageStatus.Active
        },
        configuredBudget = budget,
    )
}

internal fun budgetInlineLoadError(state: BudgetUiState): UiText? =
    state.loadError?.takeIf { state.budget != null && !state.loading }
