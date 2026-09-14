package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.screens.editInitialCategory

/** Raw field values, so a new server review cannot discard incomplete or invalid input. */
internal data class ExpenseEditFormValues(
    val currency: CurrencyCode,
    val amountText: String,
    val manualExchangeRateText: String,
    val merchant: String,
    val category: String,
    val note: String,
    val expenseTime: String,
    val tags: String,
    val valueScoreText: String,
    val regretScoreText: String,
) {
    fun changesFxIdentity(expense: Expense): Boolean {
        return currency != expense.originalCurrencyCode ||
            parseMinorAmount(amountText, currency) != expense.originalAmountMinor ||
            expenseTime != expense.expenseTime.orEmpty()
    }

    companion object {
        fun fromExpense(expense: Expense): ExpenseEditFormValues = ExpenseEditFormValues(
            currency = expense.originalCurrencyCode,
            amountText = formatMinorAmountInput(initialExpenseAmountInputMinor(expense), expense.originalCurrencyCode),
            manualExchangeRateText = expense.fxRate?.takeIf { expense.fxSource == FxContract.SourceManual }.orEmpty(),
            merchant = expense.merchant.orEmpty(),
            category = editInitialCategory(expense),
            note = expense.note.orEmpty(),
            expenseTime = expense.expenseTime.orEmpty(),
            tags = expense.tags.orEmpty(),
            valueScoreText = expense.valueScore?.toString().orEmpty(),
            regretScoreText = expense.regretScore?.toString().orEmpty(),
        )
    }
}
