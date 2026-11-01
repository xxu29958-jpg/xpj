package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.repository.toDomain
import com.ticketbox.data.repository.toCapturedTime
import com.ticketbox.domain.model.Expense
import java.time.ZoneId

/** Restore the exact rejected time choice, rather than adopting today's device timezone. */
internal fun confirmationTimeForm(expense: Expense, changes: ExpenseUpdateRequest?): String? {
    if (changes == null || (changes.timeInput == null && changes.expenseTime == null &&
            changes.spentAt == null && changes.recognitionTimeChoice == null)) return null
    val input = changes.timeInput?.toDomain()
    val instant = input?.instantUtc ?: changes.expenseTime ?: changes.spentAt ?: expense.expenseTime
    return ExpenseTimeForm.initial(instant, input?.toCapturedTime() ?: expense.accountingTime, null, ZoneId.systemDefault())
        .copy(changed = true, recognitionChoice = changes.recognitionTimeChoice).toSavedJson()
}
