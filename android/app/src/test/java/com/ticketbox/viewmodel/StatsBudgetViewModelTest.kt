package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.StatsActions
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetProgressStatus
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

@OptIn(ExperimentalCoroutinesApi::class)
class StatsBudgetViewModelTest {
    private fun budgetTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun configuredBudgetWithoutProgressKeepsConfiguredStatus() = budgetTest {
        val vm = StatsBudgetViewModel(
            statsRepository = FakeStatsBudgetStatsActions(),
            budgetRepository = FakeStatsBudgetActions(
                budget = budgetMonthly(
                    configured = true,
                    totalAmountCents = 0L,
                    spentAmountCents = 2_000L,
                ),
            ),
        )
        runCurrent()

        vm.refresh(month = "2026-07", stats = null)
        advanceUntilIdle()

        assertEquals(BudgetProgressStatus.ConfiguredWithoutProgress, vm.uiState.value.budgetProgressStatus)
        assertNull(vm.uiState.value.budgetProgress)
    }

    @Test
    fun unconfiguredBudgetDoesNotReusePositiveAmountsAsProgress() = budgetTest {
        val vm = StatsBudgetViewModel(
            statsRepository = FakeStatsBudgetStatsActions(),
            budgetRepository = FakeStatsBudgetActions(
                budget = budgetMonthly(
                    configured = false,
                    totalAmountCents = 100_000L,
                    spentAmountCents = 2_000L,
                ),
            ),
        )
        runCurrent()

        vm.refresh(month = "2026-07", stats = null)
        advanceUntilIdle()

        assertEquals(BudgetProgressStatus.Unconfigured, vm.uiState.value.budgetProgressStatus)
        assertNull(vm.uiState.value.budgetProgress)
    }
}

private class FakeStatsBudgetStatsActions : StatsActions {
    private val ledgerId = MutableStateFlow<String?>("ledger-1")

    override fun observeActiveLedgerId(): Flow<String?> = ledgerId

    override fun observeConfirmed(): Flow<List<Expense>> = emptyFlow()

    override fun monthlyBudgetCents(): Long? = null

    override fun lastUploadAt(): String? = null

    override suspend fun months(): Result<List<String>> = Result.success(emptyList())

    override suspend fun tags(): Result<List<String>> = Result.success(emptyList())

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> =
        Result.failure(UnsupportedOperationException())

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> =
        Result.failure(UnsupportedOperationException())

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = Result.success(emptyList())

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> =
        Result.failure(UnsupportedOperationException())
}

private class FakeStatsBudgetActions(
    private val budget: BudgetMonthly,
) : BudgetActions {
    override fun canModifyLedger(): Boolean = true

    override fun currentHomeCurrency(): CurrencyCode = CurrencyCode.CNY

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> = Result.success(budget.copy(month = month))

    override suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult> =
        Result.failure(UnsupportedOperationException())

    override suspend fun saveMonthlyBudget(
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly> = Result.failure(UnsupportedOperationException())
}

private fun budgetMonthly(
    configured: Boolean,
    totalAmountCents: Long,
    spentAmountCents: Long,
): BudgetMonthly = BudgetMonthly(
    ledgerId = "ledger-1",
    month = "2026-07",
    configured = configured,
    totalAmountCents = totalAmountCents,
    rolloverAmountCents = 0L,
    fixedAmountCents = 0L,
    nonMonthlyAmountCents = 0L,
    flexBudgetCents = totalAmountCents,
    spentAmountCents = spentAmountCents,
    excludedAmountCents = 0L,
    remainingAmountCents = totalAmountCents - spentAmountCents,
    overspentAmountCents = (spentAmountCents - totalAmountCents).coerceAtLeast(0L),
    excludedCategories = emptyList(),
    excludedBreakdown = emptyList(),
    categoryBudgets = emptyList(),
    updatedAt = "2026-07-05T00:00:00Z",
    rowVersion = if (configured) 1L else null,
)
