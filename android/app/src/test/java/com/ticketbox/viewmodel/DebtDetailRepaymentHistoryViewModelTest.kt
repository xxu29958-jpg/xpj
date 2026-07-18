package com.ticketbox.viewmodel

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtDetailRepaymentHistoryViewModelTest {
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
    fun loadMoreAppendsFiftyFirstFactWithoutDuplicatingOverlap() = runTest(dispatcher) {
        val expectedIds = (51 downTo 1).map { "repayment-$it" }
        val repository = FakeDebtDetailActions(
            historyResult = Result.success(
                repaymentHistoryPage("d1", page = 1, total = 51, publicIds = expectedIds.take(50)),
            ),
        ).apply {
            historyPageResults[2] = Result.success(
                repaymentHistoryPage(
                    "d1",
                    page = 2,
                    total = 51,
                    publicIds = listOf("repayment-2", "repayment-1"),
                ),
            )
        }
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        assertTrue(viewModel.state.value.repaymentHistory?.hasMore == true)
        viewModel.loadMoreRepaymentHistory()
        advanceUntilIdle()

        val history = viewModel.state.value.repaymentHistory
        assertEquals(expectedIds, history?.items?.map { it.publicId })
        assertEquals(51, history?.items?.map { it.publicId }?.toSet()?.size)
        assertEquals(2, history?.page)
        assertEquals(false, history?.hasMore)
        assertEquals(
            listOf(RepaymentHistoryArgs("d1", 1), RepaymentHistoryArgs("d1", 2)),
            repository.historyCalls,
        )
    }

    @Test
    fun loadMoreFailureKeepsFirstPageReadableAndRetryable() = runTest(dispatcher) {
        val firstPage = repaymentHistoryPage(
            debtPublicId = "d1",
            page = 1,
            total = 51,
            publicIds = (51 downTo 2).map { "repayment-$it" },
        )
        val repository = FakeDebtDetailActions(historyResult = Result.success(firstPage)).apply {
            historyPageResults[2] = Result.failure(RuntimeException("history page offline"))
        }
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.loadMoreRepaymentHistory()
        advanceUntilIdle()

        assertEquals(firstPage.items, viewModel.state.value.repaymentHistory?.items)
        assertNull(viewModel.state.value.repaymentHistoryError)
        assertTrue(viewModel.state.value.repaymentHistoryLoadMoreError != null)
        assertEquals(false, viewModel.state.value.isRepaymentHistoryLoadingMore)
        viewModel.openAction(DebtAction.RepaymentVoid, "repayment-51")
        assertEquals(DebtAction.RepaymentVoid, viewModel.state.value.activeAction)
    }
}
