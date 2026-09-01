package com.ticketbox.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

/** A1 retirement: the legacy editor may identify a confirmed row, but not consume its details. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseEditViewModelConfirmedHandoffTest {
    @Test
    fun `confirmed handoff loads only the status snapshot`() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val fake = FakeExpenseEditActions().apply {
                fetchExpenseResponder = {
                    Result.success(
                        baseExpense.copy(status = "confirmed", amountCents = 1000L),
                    )
                }
            }

            val viewModel = ExpenseEditViewModel(expenseId = 7L, repository = fake)
            advanceUntilIdle()

            assertEquals("confirmed", viewModel.uiState.value.expense?.status)
            assertEquals(0, fake.categoriesCalls)
            assertEquals(0, fake.fetchThumbnailCalls)
            assertEquals(0, fake.fetchItemsCalls)
            assertEquals(0, fake.fetchSplitsCalls)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun `confirmed handoff falls back to its cached snapshot when offline`() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val fake = FakeExpenseEditActions().apply {
                fetchExpenseResponder = { Result.failure(IllegalStateException("offline")) }
                localCacheResponder = {
                    Result.success(baseExpense.copy(status = "confirmed", amountCents = 1000L))
                }
            }

            val viewModel = ExpenseEditViewModel(expenseId = 7L, repository = fake)
            advanceUntilIdle()

            assertEquals("confirmed", viewModel.uiState.value.expense?.status)
            assertEquals(1, fake.localCacheCalls)
            assertEquals(0, fake.categoriesCalls)
            assertEquals(0, fake.fetchItemsCalls)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }
}
