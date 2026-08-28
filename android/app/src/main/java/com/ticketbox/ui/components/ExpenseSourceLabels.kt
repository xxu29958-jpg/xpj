package com.ticketbox.ui.components

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseSourceValues

/** Maps persisted Expense.source tokens to shared localized presentation labels. */
@StringRes
internal fun expenseSourceLabelRes(source: String): Int? {
    if (source.startsWith(ExpenseSourceValues.NOTIFICATION_DRAFT_PREFIX)) {
        return R.string.expense_edit_source_notification
    }
    return when (source) {
        ExpenseSourceValues.IPHONE_SCREENSHOT -> R.string.expense_edit_source_iphone
        ExpenseSourceValues.ANDROID_SCREENSHOT -> R.string.expense_edit_source_android
        ExpenseSourceValues.WEB_UPLOAD -> R.string.expense_edit_source_web
        ExpenseSourceValues.MANUAL_ENTRY -> R.string.expense_edit_source_manual
        ExpenseSourceValues.CSV_IMPORT -> R.string.expense_edit_source_csv
        ExpenseSourceValues.BILL_SPLIT_RECEIVED -> R.string.expense_edit_source_bill_split
        else -> null
    }
}
