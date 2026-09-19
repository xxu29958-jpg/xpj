package com.ticketbox.ui.components

import com.ticketbox.domain.model.Expense
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto

/** A financial day and a known clock time are separate labels; confirmation is never purchase evidence. */
fun expenseAccountingDayLabel(expense: Expense): String? = expense.accountingTime?.accountingDate

fun expenseKnownInstant(expense: Expense): String? = when (expense.accountingTime?.precision) {
    "date_only", "unknown" -> null
    "instant" -> expense.accountingTime.instantUtc
    else -> expense.expenseTime
}

fun expenseTimeLabel(expense: Expense): String =
    expenseAccountingDayLabel(expense) ?: expenseKnownInstant(expense)?.let(::displayDateTime) ?: "消费日期待补充"

fun expenseClockLabel(expense: Expense): String = expenseKnownInstant(expense)?.let(::displayTime)
    ?: if (expense.accountingTime?.precision == "date_only") "仅日期" else "时间未知"

fun timeInputLabel(input: ExpenseTimeInputDto): String = if (input.precision == "date_only") {
    "${input.accountingDate ?: input.userLocalDate} · 仅日期"
} else {
    listOfNotNull(input.userLocalDate, input.instantUtc?.let(::displayDateTime), input.sourceTimezone).joinToString(" · ")
}
