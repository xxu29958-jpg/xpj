package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
import com.ticketbox.presentation.formatMinorAmountInput
import com.ticketbox.presentation.parseMinorAmount
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
    val categoryChoice: String? = null,
    val categoryDecisionPublicId: String? = null,
    val recognitionFieldChoicesJson: String? = null,
    val originalTextFeedbackJson: String? = null,
) {
    fun changesFxIdentity(expense: Expense): Boolean {
        return currency != expense.originalCurrencyCode ||
            parseMinorAmount(amountText, currency) != expense.originalAmountMinor ||
            expenseTime != expense.expenseTime.orEmpty()
    }

    companion object {
        /** Every raw field and date picker shares one adoption identity, including attachment-only review. */
        fun identity(expense: Expense, formRevision: Int, preservedTimestamp: String?): String =
            "${expense.id}:${preservedTimestamp ?: expense.updatedAt}:$formRevision"

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

        fun fromConfirmation(expense: Expense, changes: com.ticketbox.data.remote.dto.ExpenseUpdateRequest?): ExpenseEditFormValues {
            val baseline = fromExpense(expense)
            if (changes == null) return baseline
            return baseline.copy(
                currency = changes.originalCurrency?.let { requireNotNull(CurrencyCode.fromStorageKeyOrNull(it)) } ?: baseline.currency,
                amountText = changes.originalAmount ?: baseline.amountText,
                manualExchangeRateText = changes.manualExchangeRate ?: baseline.manualExchangeRateText,
                merchant = changes.merchant ?: baseline.merchant, category = changes.category ?: baseline.category,
                note = changes.note ?: baseline.note, tags = changes.tags ?: baseline.tags,
                expenseTime = confirmationInstant(changes) ?: baseline.expenseTime,
                valueScoreText = changes.valueScore?.toString() ?: baseline.valueScoreText,
                regretScoreText = changes.regretScore?.toString() ?: baseline.regretScoreText,
                categoryChoice = changes.categoryChoice, categoryDecisionPublicId = changes.categoryDecisionPublicId,
                recognitionFieldChoicesJson = changes.recognitionFieldChoices.orEmpty().fold(null as String?) { raw, choice ->
                    updateFieldChoice(raw, choice.field, choice) },
                originalTextFeedbackJson = changes.originalTextFeedback.orEmpty().fold(null as String?) { raw, feedback ->
                    updateOriginalFeedback(raw, feedback.field, feedback) },
            )
        }
    }
}

private fun confirmationInstant(changes: com.ticketbox.data.remote.dto.ExpenseUpdateRequest): String? =
    changes.timeInput?.instantUtc ?: changes.expenseTime ?: changes.spentAt
