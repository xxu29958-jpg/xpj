package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtRepaymentHistory
import com.ticketbox.domain.model.DebtRepaymentRecord

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

internal fun canVoidRepayment(
    debt: Debt,
    history: DebtRepaymentHistory?,
    repayment: DebtRepaymentRecord,
    canModify: Boolean,
    historyIsFresh: Boolean,
): Boolean = canModify &&
    historyIsFresh &&
    debt.isDirectWritable &&
    !debt.isVoided &&
    history?.debtPublicId == debt.publicId &&
    repayment.isActive &&
    history.items.any { it.publicId == repayment.publicId }
