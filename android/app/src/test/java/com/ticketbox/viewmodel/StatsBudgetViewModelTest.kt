package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.BudgetProgressStatus
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
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
            budgetRepository = FakeStatsBudgetActions(
                budget = budgetMonthly(
                    configured = true,
                    totalAmountCents = 0L,
                    spentAmountCents = 2_000L,
                ),
            ),
        )
        runCurrent()

        vm.refresh(month = "2026-07")
        advanceUntilIdle()

        assertEquals(BudgetProgressStatus.ConfiguredWithoutProgress, vm.uiState.value.budgetProgressStatus)
        assertNull(vm.uiState.value.budgetProgress)
    }

    @Test
    fun unconfiguredBudgetDoesNotReusePositiveAmountsAsProgress() = budgetTest {
        val vm = StatsBudgetViewModel(
            budgetRepository = FakeStatsBudgetActions(
                budget = budgetMonthly(
                    configured = false,
                    totalAmountCents = 100_000L,
                    spentAmountCents = 2_000L,
                ),
            ),
        )
        runCurrent()

        vm.refresh(month = "2026-07")
        advanceUntilIdle()

        assertEquals(BudgetProgressStatus.Unconfigured, vm.uiState.value.budgetProgressStatus)
        assertNull(vm.uiState.value.budgetProgress)
    }

    @Test
    fun replacingSameNamedLedgerClearsBudgetAndReadsWithExactBinding() = budgetTest {
        val owner = FakeStatsBudgetActions(budgetMonthly(true, 100000, 2000))
        val original = requireNotNull(owner.access.value).binding
        val vm = StatsBudgetViewModel(owner)
        runCurrent()
        vm.refresh("2026-07")
        advanceUntilIdle()
        assertEquals(100000L, vm.uiState.value.budgetProgress?.budgetCents)
        val replacement = original.copy(ownerKey = "second-owner", sessionGeneration = "second-session")
        val response = CompletableDeferred<BudgetMonthly>()
        owner.responder = { response.await() }
        owner.access.value = LedgerAccessContext(replacement, canModify = true)
        owner.budget = owner.budget.copy(totalAmountCents = 5000, homeCurrencyCode = "JPY")
        advanceUntilIdle()
        assertNull(vm.uiState.value.budgetProgress, "same ledger name does not identify the same household")
        response.complete(owner.budget)
        advanceUntilIdle()
        assertEquals(5000L, vm.uiState.value.budgetProgress?.budgetCents)
        assertEquals("JPY", vm.uiState.value.budgetProgress?.homeCurrencyCode)
        assertEquals(listOf(original, replacement), owner.requestedBindings)
    }

    @Test
    fun returningToAnInflightMonthPublishesThatMonthsResponse() = budgetTest {
        val july = CompletableDeferred<BudgetMonthly>()
        val august = CompletableDeferred<BudgetMonthly>()
        val owner = FakeStatsBudgetActions(budgetMonthly(true, 100000, 2000))
        owner.responder = { if (it == "2026-07") july.await() else august.await() }
        val vm = StatsBudgetViewModel(owner)
        // Refresh may precede the first identity emission.
        vm.refresh("2026-07")
        runCurrent()
        vm.refresh("2026-08")
        runCurrent()
        vm.refresh("2026-07")
        august.complete(owner.budget.copy(month = "2026-08", totalAmountCents = 8000))
        runCurrent()
        assertNull(vm.uiState.value.budgetProgress)
        july.complete(owner.budget)
        advanceUntilIdle()
        assertEquals("2026-07", vm.uiState.value.month)
        assertEquals(100000L, vm.uiState.value.budgetProgress?.budgetCents)
        assertEquals(2, owner.requestedBindings.size)
        vm.refresh("2026-08")
        assertEquals(8000L, vm.uiState.value.budgetProgress?.budgetCents)
        assertEquals(2, owner.requestedBindings.size)
    }
}

private class FakeStatsBudgetActions(
    var budget: BudgetMonthly,
) : BudgetActions {
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(
        LogicalSessionBinding("https://example.test", "ledger-1", "owner", "session", "binding"), true))
    val requestedBindings = mutableListOf<LogicalSessionBinding>()
    var responder: (suspend (String) -> BudgetMonthly)? = null
    override fun canModifyLedger(): Boolean = true

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = access

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> = Result.success(responder?.invoke(month) ?: budget.copy(month = month))

    override suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult> =
        Result.failure(UnsupportedOperationException())

    override suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
    ): Result<BudgetMonthly> {
        requestedBindings += expectedBinding
        return monthlyBudget(month)
    }

    override fun observeSaves(expectedBinding: LogicalSessionBinding): Flow<List<com.ticketbox.data.repository.PendingBudgetSave>> = flowOf(emptyList())
    override suspend fun recoverSave(expectedBinding: LogicalSessionBinding, pending: com.ticketbox.data.repository.PendingBudgetSave, drop: Boolean): Result<Unit> = Result.failure(UnsupportedOperationException())

    override suspend fun enqueueSave(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<Long> = Result.failure(UnsupportedOperationException())
}

private fun budgetMonthly(
    configured: Boolean,
    totalAmountCents: Long,
    spentAmountCents: Long,
): BudgetMonthly = BudgetMonthly(
    homeCurrencyCode = "CNY",
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
