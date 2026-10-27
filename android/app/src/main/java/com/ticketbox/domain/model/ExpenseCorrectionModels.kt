package com.ticketbox.domain.model

data class CorrectionIntChange(
    val changed: Boolean,
    val value: Int?,
) {
    companion object {
        fun unchanged() = CorrectionIntChange(false, null)
        fun changed(value: Int?) = CorrectionIntChange(true, value)
    }
}

data class CorrectionStringChange(
    val changed: Boolean,
    val value: String?,
) {
    companion object {
        fun unchanged() = CorrectionStringChange(false, null)
        fun changed(value: String?) = CorrectionStringChange(true, value)
    }
}

data class CorrectionTimeChange(
    val changed: Boolean, val value: ExpenseTimeInput?
) {
    companion object {
        fun unchanged() = CorrectionTimeChange(false, null)
        fun changed(value: ExpenseTimeInput?) = CorrectionTimeChange(true, value)
    }
}

data class ExpenseCorrectionSubmission(
    val expectedRowVersion: Long,
    val reason: String,
    val amountCents: Long? = null,
    val originalCurrencyCode: String? = null,
    val originalAmountMinor: Long? = null,
    val merchant: String? = null,
    val category: String? = null,
    val categoryChoice: String? = null,
    val note: String? = null,
    val expenseTime: CorrectionStringChange = CorrectionStringChange.unchanged(),
    val tags: String? = null,
    val valueScore: CorrectionIntChange = CorrectionIntChange.unchanged(),
    val regretScore: CorrectionIntChange = CorrectionIntChange.unchanged(),
    val items: List<ExpenseItemDraft>? = null,
    val splits: List<ExpenseSplitDraft>? = null,
    val timeInput: CorrectionTimeChange = CorrectionTimeChange.unchanged(),
)
