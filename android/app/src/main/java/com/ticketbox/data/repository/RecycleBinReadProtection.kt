package com.ticketbox.data.repository

import com.ticketbox.domain.model.RecycleBinItem
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

/** Restore uses each fact owner's existing read fence and invalidation path. */
internal class RecycleBinReadProtection(
    private val budgets: BudgetQueryReader,
    private val recurring: RecurringQueryReader,
    private val income: IncomeQueryReader,
    private val goals: GoalQueryReader,
) {
    suspend fun restore(binding: LogicalSessionBinding, item: RecycleBinItem, restore: suspend () -> String): String =
        when (item.kind) {
            "monthly_budget" -> budgets.directMutation(binding, item.resourceId) { restore() }
            "recurring_item" -> recurring.directMutation(binding) { restore() }
            "income_plan" -> income.directWrite(binding) { restore() }
            "goal" -> {
                val result = restore()
                withContext(NonCancellable) { goals.invalidate(binding) }
                result
            }
            else -> restore()
        }
}
