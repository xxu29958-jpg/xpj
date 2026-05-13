package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class BudgetViewModelTest {
    private fun budgetTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun initialLoadPopulatesBudgetAndForm() = budgetTest {
        val fake = FakeBudgetActions(
            budget = budget(
                totalAmountCents = 500000,
                rolloverAmountCents = -20000,
                categoryBudgets = listOf(categoryBudget("餐饮", 120000)),
            ),
        )

        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.loading)
        assertEquals("2026-05", state.month)
        assertEquals(500000L, state.budget?.totalAmountCents)
        assertEquals("5000", state.form.totalAmount)
        assertEquals("-200", state.form.rolloverAmount)
        assertEquals("餐饮", state.form.categoryRows.single().category)
        assertEquals(1, fake.loadCalls)
    }

    @Test
    fun saveBuildsUpdateAndReloadsReturnedBudget() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(configured = false))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount(" 3000 ")
        vm.updateRolloverAmount("-100")
        vm.updateNonMonthlyAmount("200")
        vm.updateExcludedCategories(" 医疗，报销 ")
        vm.updateCategoryRow(0, " 吃饭 ", "1200")
        vm.save()
        advanceUntilIdle()

        val request = fake.savedRequests.single()
        assertEquals("2026-05", fake.savedMonths.single())
        assertEquals(300000L, request.totalAmountCents)
        assertEquals(-10000L, request.rolloverAmountCents)
        assertEquals(20000L, request.nonMonthlyAmountCents)
        assertEquals(listOf("医疗", "报销"), request.excludedCategories)
        assertEquals("吃饭", request.categoryBudgets.single().category)
        assertEquals(120000L, request.categoryBudgets.single().amountCents)
        assertEquals("预算已保存。", vm.uiState.value.message)
    }

    @Test
    fun saveRejectsInvalidAmountsBeforeRepositoryCall() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(configured = false))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount("3000")
        vm.updateNonMonthlyAmount("-1")
        vm.save()
        advanceUntilIdle()

        assertEquals(0, fake.savedRequests.size)
        assertEquals("非月度预留 不能为负数。", vm.uiState.value.message)
    }

    @Test
    fun viewerSaveShortCircuitsWithoutRepositoryCall() = budgetTest {
        val fake = FakeBudgetActions(
            budget = budget(configured = true),
            canModify = false,
        )
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount("3000")
        vm.save()
        advanceUntilIdle()

        assertEquals(0, fake.savedRequests.size)
        assertEquals(READ_ONLY_LEDGER_MESSAGE, vm.uiState.value.message)
        assertFalse(vm.uiState.value.canModify)
    }

    @Test
    fun monthChangeLoadsRequestedMonth() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(month = "2026-05"))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        fake.budget = budget(month = "2026-04")
        vm.previousMonth()
        advanceUntilIdle()

        assertEquals(listOf("2026-05", "2026-04"), fake.loadedMonths)
        assertEquals("2026-04", vm.uiState.value.month)
        assertNull(vm.uiState.value.message)
    }
}

private class FakeBudgetActions(
    var budget: BudgetMonthly,
    private val canModify: Boolean = true,
) : BudgetActions {
    val loadedMonths = mutableListOf<String>()
    val savedMonths = mutableListOf<String>()
    val savedRequests = mutableListOf<BudgetMonthlyUpdate>()
    val loadCalls: Int get() = loadedMonths.size

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> {
        loadedMonths += month
        return Result.success(budget.copy(month = month))
    }

    override suspend fun saveMonthlyBudget(
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly> {
        savedMonths += month
        savedRequests += update
        budget = budget.copy(
            month = month,
            configured = true,
            totalAmountCents = update.totalAmountCents,
            rolloverAmountCents = update.rolloverAmountCents,
            nonMonthlyAmountCents = update.nonMonthlyAmountCents,
        )
        return Result.success(budget)
    }
}

private fun budget(
    month: String = "2026-05",
    configured: Boolean = true,
    totalAmountCents: Long = 300000,
    rolloverAmountCents: Long = 0,
    categoryBudgets: List<BudgetCategoryBudget> = emptyList(),
): BudgetMonthly = BudgetMonthly(
    ledgerId = "owner",
    month = month,
    configured = configured,
    totalAmountCents = totalAmountCents,
    rolloverAmountCents = rolloverAmountCents,
    fixedAmountCents = 50000,
    nonMonthlyAmountCents = 10000,
    flexBudgetCents = 240000,
    spentAmountCents = 120000,
    excludedAmountCents = 0,
    remainingAmountCents = totalAmountCents + rolloverAmountCents - 120000,
    overspentAmountCents = 0,
    excludedCategories = emptyList(),
    excludedBreakdown = emptyList(),
    categoryBudgets = categoryBudgets,
    updatedAt = "2026-05-13T00:00:00Z",
)

private fun categoryBudget(category: String, amountCents: Long): BudgetCategoryBudget = BudgetCategoryBudget(
    category = category,
    amountCents = amountCents,
    spentAmountCents = 30000,
    remainingAmountCents = amountCents - 30000,
    overspentAmountCents = 0,
)
