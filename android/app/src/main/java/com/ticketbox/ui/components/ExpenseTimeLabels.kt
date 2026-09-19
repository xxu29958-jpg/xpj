package com.ticketbox.ui.components

import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.UiText
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto

/** A financial day and a known clock time are separate labels; confirmation is never purchase evidence. */
fun expenseAccountingDayLabel(expense: Expense): String? = expense.accountingTime?.accountingDate

fun expenseKnownInstant(expense: Expense): String? = when (expense.accountingTime?.precision) {
    "date_only", "unknown" -> null
    "instant" -> expense.accountingTime.instantUtc
    else -> expense.expenseTime
}

fun expenseTimeLabel(expense: Expense): UiText =
    (expenseAccountingDayLabel(expense) ?: expenseKnownInstant(expense)?.let(::displayDateTime))?.let(UiText::raw)
        ?: UiText.res(R.string.calendar_date_pending)

fun expenseClockLabel(expense: Expense): UiText = when {
    expense.accountingTime != null && expense.accountingTime.accountingDate == null -> UiText.res(R.string.calendar_date_pending)
    expenseKnownInstant(expense) != null -> UiText.raw(displayTime(expenseKnownInstant(expense)))
    expense.accountingTime?.precision == "date_only" -> UiText.res(R.string.calendar_date_only_label)
    else -> UiText.res(R.string.calendar_clock_unknown)
}

fun timeInputLabel(input: ExpenseTimeInputDto): UiText = if (input.precision == "date_only") {
    UiText.compound(listOf(UiText.raw(input.accountingDate ?: input.userLocalDate), UiText.res(R.string.calendar_date_only_label)), " · ")
} else {
    UiText.raw(listOfNotNull(input.userLocalDate, input.instantUtc?.let(::displayDateTime), input.sourceTimezone).joinToString(" · "))
}
