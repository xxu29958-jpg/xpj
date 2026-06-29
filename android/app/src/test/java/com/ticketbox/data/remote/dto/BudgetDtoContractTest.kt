package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class BudgetDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun budgetMonthlyParsesCurrentServerShapeAndSerializesUpdate() {
        val dto = requireNotNull(
            moshi.adapter(BudgetMonthlyDto::class.java).fromJson(
                """
                {
                  "ledger_id": "owner",
                  "month": "2026-05",
                  "configured": true,
                  "row_version": 3,
                  "total_amount_cents": 500000,
                  "rollover_amount_cents": -20000,
                  "fixed_amount_cents": 98000,
                  "non_monthly_amount_cents": 30000,
                  "flex_budget_cents": 352000,
                  "spent_amount_cents": 126800,
                  "excluded_amount_cents": 45000,
                  "remaining_amount_cents": 353200,
                  "overspent_amount_cents": 0,
                  "excluded_categories": ["医疗"],
                  "excluded_breakdown": [
                    {"category": "医疗", "amount_cents": 45000, "count": 1}
                  ],
                  "category_budgets": [
                    {
                      "category": "餐饮",
                      "amount_cents": 120000,
                      "spent_amount_cents": 58000,
                      "remaining_amount_cents": 62000,
                      "overspent_amount_cents": 0
                    }
                  ],
                  "updated_at": "2026-05-13T00:00:00Z"
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(BudgetMonthlyUpdateRequestDto::class.java).toJson(
            BudgetMonthlyUpdateRequestDto(
                totalAmountCents = 500000,
                nonMonthlyAmountCents = 30000,
                rolloverAmountCents = -20000,
                excludedCategories = listOf("医疗"),
                categoryBudgets = listOf(BudgetCategoryRequestDto("餐饮", 120000)),
            ),
        )

        assertEquals("owner", dto.ledgerId)
        assertEquals("2026-05", dto.month)
        assertEquals(3L, dto.rowVersion)
        assertEquals(352000L, dto.flexBudgetCents)
        assertEquals(-20000L, dto.rolloverAmountCents)
        assertEquals("医疗", dto.excludedBreakdown.single().category)
        assertEquals("餐饮", dto.categoryBudgets.single().category)
        assertEquals(
            """{"total_amount_cents":500000,"non_monthly_amount_cents":30000,"rollover_amount_cents":-20000,"excluded_categories":["医疗"],"category_budgets":[{"category":"餐饮","amount_cents":120000}]}""",
            requestJson,
        )
    }
}
