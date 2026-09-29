package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense

interface ExpenseRootReadActions {
    suspend fun fetchExpense(id: Long, expectedBinding: LogicalSessionBinding? = null): Result<Expense>
    suspend fun fetchExpenseFromLocalCache(id: Long, expectedBinding: LogicalSessionBinding? = null): Result<Expense>
}
