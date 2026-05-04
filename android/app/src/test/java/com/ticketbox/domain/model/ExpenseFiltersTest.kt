package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseFiltersTest {
    @Test
    fun filtersByExpenseTimeMonthAndCategory() {
        val items = listOf(
            expense(id = 1, category = "吃饭", expenseTime = "2026-05-03T04:20:00Z"),
            expense(id = 2, category = "交通", expenseTime = "2026-05-04T04:20:00Z"),
            expense(id = 3, category = "吃饭", expenseTime = "2026-06-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(items, month = "2026-05", category = "吃饭")

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    @Test
    fun fallsBackToConfirmedAtWhenExpenseTimeIsBlank() {
        val items = listOf(
            expense(id = 1, category = "购物", expenseTime = null, confirmedAt = "2026-05-03T04:20:00Z"),
            expense(id = 2, category = "购物", expenseTime = null, confirmedAt = "2026-04-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(items, month = "2026-05", category = "")

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    private fun expense(
        id: Long,
        category: String,
        expenseTime: String?,
        confirmedAt: String? = "2026-05-03T04:20:00Z",
    ): Expense {
        return Expense(
            id = id,
            amountCents = 100,
            merchant = "测试商家",
            category = category,
            note = null,
            source = "iPhone截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = expenseTime,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = "2026-05-01T00:00:00Z",
            confirmedAt = confirmedAt,
            rejectedAt = null,
        )
    }
}
