package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.Expense

internal fun initialExpenseAmountInputMinor(expense: Expense): Long? =
    expense.originalAmountMinor ?: expense.amountCents
