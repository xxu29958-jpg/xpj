package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText

internal enum class DebtDetailBodyState {
    Loading,
    LoadFailed,
    Content,
}

internal fun debtDetailBodyState(
    hasDebt: Boolean,
    isLoading: Boolean,
    error: UiText?,
): DebtDetailBodyState = when {
    hasDebt -> DebtDetailBodyState.Content
    isLoading -> DebtDetailBodyState.Loading
    error != null -> DebtDetailBodyState.LoadFailed
    else -> DebtDetailBodyState.Loading
}

internal fun debtDetailInlineMessage(
    bodyState: DebtDetailBodyState,
    message: UiText?,
): UiText? = message?.takeIf { bodyState == DebtDetailBodyState.Content }
