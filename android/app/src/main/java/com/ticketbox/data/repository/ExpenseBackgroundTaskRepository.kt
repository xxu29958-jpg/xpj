package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask

internal class ExpenseBackgroundTaskRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun fetchExpenseFx(binding: LogicalSessionBinding, id: Long): Result<BackgroundTask?> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        bound.call { it.expenseFx(id) }?.toDomain()
    }

    suspend fun retryExpenseFx(binding: LogicalSessionBinding, expense: com.ticketbox.domain.model.Expense): Result<BackgroundTask> =
        core.errorHandler.safeCall {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            if (!core.canModifyLedger()) throw RepositoryException("当前角色为只读，无法重新换算。")
            require(expense.id > 0 && expense.status == "pending")
            bound.call {
                it.retryExpenseFx(expense.id, com.ticketbox.data.remote.dto.ExpenseStateTokenRequest(expense.rowVersion))
            }.toDomain()
        }

    suspend fun fetchExpenseForFxReview(binding: LogicalSessionBinding, id: Long): Result<com.ticketbox.domain.model.Expense> =
        core.errorHandler.safeCall {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            core.fetchAuthoritativeExpense(bound, id).toDomain()
        }

    suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        bound.call { it.listBackgroundTasks() }.items.map { it.toDomain() }
    }

    suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        bound.call { it.cancelBackgroundTask(publicId) }.toDomain()
    }
}
