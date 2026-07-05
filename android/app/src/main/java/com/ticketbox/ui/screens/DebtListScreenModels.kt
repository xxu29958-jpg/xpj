package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.DebtListUiState

internal enum class DebtListBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun debtListBodyState(state: DebtListUiState): DebtListBodyState = when {
    state.debts.isNotEmpty() -> DebtListBodyState.Content
    state.isLoading -> DebtListBodyState.Loading
    state.error != null -> DebtListBodyState.LoadFailed
    else -> DebtListBodyState.Empty
}

internal fun debtListInlineError(state: DebtListUiState): UiText? =
    state.error?.takeIf { debtListBodyState(state) == DebtListBodyState.Content }
