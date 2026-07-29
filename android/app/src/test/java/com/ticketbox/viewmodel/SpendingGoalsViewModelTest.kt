package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull

@OptIn(ExperimentalCoroutinesApi::class)
class SpendingGoalsViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun initialLoadUsesMonthFiltersOtherGoalTypesAndPreservesViewerRole() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions(
            canModify = false,
            goalsResult = Result.success(
                listOf(
                    spendingGoal(publicId = "spending"),
                    spendingGoal(publicId = "debt", goalType = "debt_repayment"),
                    spendingGoal(publicId = "archived", status = "archived"),
                ),
            ),
        )
        val viewModel = SpendingGoalsViewModel(actions, CapabilityDebtActions(), initialMonth = "2026-07")
        advanceUntilIdle()

        assertEquals(SpendingGoalListCall("2026-07", false), actions.goalsCalls.single())
        assertEquals(listOf("spending"), viewModel.state.value.goals.map { it.publicId })
        assertFalse(viewModel.state.value.canModify)
        assertFalse(viewModel.state.value.isLoading)
    }

    @Test
    fun monthNavigationReloadsTheSelectedMonth() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions()
        val viewModel = SpendingGoalsViewModel(actions, CapabilityDebtActions(), initialMonth = "2026-07")
        advanceUntilIdle()

        viewModel.nextMonth()
        advanceUntilIdle()

        assertEquals("2026-08", viewModel.state.value.month)
        assertEquals("2026-08", actions.goalsCalls.last().month)
    }

    @Test
    fun failedLoadCanBeRetriedWithoutKeepingTheError() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions(
            goalsResult = Result.failure(IllegalStateException("offline")),
        )
        val viewModel = SpendingGoalsViewModel(actions, CapabilityDebtActions(), initialMonth = "2026-07")
        advanceUntilIdle()
        assertNotNull(viewModel.state.value.loadError)

        actions.goalsResult = Result.success(listOf(spendingGoal()))
        viewModel.refresh()
        advanceUntilIdle()

        assertEquals(listOf("goal-1"), viewModel.state.value.goals.map { it.publicId })
        assertEquals(null, viewModel.state.value.loadError)
    }

    @Test
    fun ledgerCurrencyResolvesFromSharedRecordCapabilityVerdict() = runTest(dispatcher) {
        // 遗留 U3：列表 VM 解析账本币种供卡面显示（R14-6 共享裁决）—— JPY 信封 →
        // state.ledgerCurrency=JPY（卡面 ¥1,200 不 ¥12.00 的口径源）；未知码 → null 兜底展示。
        val jpy = SpendingGoalsViewModel(
            RecordingSpendingGoalActions(),
            CapabilityDebtActions(page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY")),
            initialMonth = "2026-07",
        )
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, jpy.state.value.ledgerCurrency)

        val unknown = SpendingGoalsViewModel(
            RecordingSpendingGoalActions(),
            CapabilityDebtActions(page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "VND")),
            initialMonth = "2026-07",
        )
        advanceUntilIdle()
        assertEquals(null, unknown.state.value.ledgerCurrency)
    }
}
