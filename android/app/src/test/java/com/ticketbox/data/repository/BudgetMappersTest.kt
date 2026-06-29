package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetCategoryDto
import com.ticketbox.data.remote.dto.BudgetExcludedCategoryDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BudgetMappersTest {
    @Test
    fun monthlyBudgetDtoMapsToDomainAndNormalizesCategories() {
        val budget = BudgetMonthlyDto(
            ledgerId = "owner",
            month = "2026-05",
            configured = true,
            totalAmountCents = 300000,
            rolloverAmountCents = -20000,
            fixedAmountCents = 50000,
            nonMonthlyAmountCents = 10000,
            flexBudgetCents = 220000,
            spentAmountCents = 320000,
            excludedAmountCents = 45000,
            remainingAmountCents = -40000,
            overspentAmountCents = 40000,
            excludedCategories = listOf("吃饭", "医疗", "餐饮"),
            excludedBreakdown = listOf(BudgetExcludedCategoryDto("吃饭", 12000, 2)),
            categoryBudgets = listOf(
                BudgetCategoryDto(
                    category = "吃饭",
                    amountCents = 100000,
                    spentAmountCents = 120000,
                    remainingAmountCents = -20000,
                    overspentAmountCents = 20000,
                ),
            ),
            updatedAt = "2026-05-13T00:00:00Z",
            rowVersion = 4,
        ).toDomain()

        assertEquals("owner", budget.ledgerId)
        assertEquals(-20000L, budget.rolloverAmountCents)
        assertEquals(4L, budget.rowVersion)
        assertEquals(-40000L, budget.remainingAmountCents)
        assertTrue(budget.isOverBudget)
        assertEquals(listOf("餐饮", "医疗"), budget.excludedCategories)
        assertEquals("餐饮", budget.excludedBreakdown.single().category)
        assertEquals("餐饮", budget.categoryBudgets.single().category)
    }

    @Test
    fun budgetUpdateMapsToSnakeCaseRequestAndNormalizesRows() {
        val request = BudgetMonthlyUpdate(
            totalAmountCents = 300000,
            nonMonthlyAmountCents = 10000,
            rolloverAmountCents = -20000,
            excludedCategories = listOf("吃饭", "医疗", "餐饮"),
            categoryBudgets = listOf(
                BudgetCategoryDraft("吃饭", 100000),
                BudgetCategoryDraft("餐饮", 120000),
            ),
        ).toRequest()

        assertEquals(300000L, request.totalAmountCents)
        assertEquals(-20000L, request.rolloverAmountCents)
        assertEquals(listOf("餐饮", "医疗"), request.excludedCategories)
        assertEquals(1, request.categoryBudgets.size)
        assertEquals("餐饮", request.categoryBudgets.single().category)
        assertEquals(100000L, request.categoryBudgets.single().amountCents)
    }
}
