package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtRepaymentQueries
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtRepaymentPage
import com.ticketbox.domain.model.DebtRepaymentVoid
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import java.io.IOException
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtRepaymentHistoryViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun pageNavigationReplacesRatherThanMergesIndependentResponses() = runTest(dispatcher) {
        val queries = DebtRepaymentQueries { id, page -> Result.success(historyPage(id, page)) }
        val viewModel = DebtRepaymentHistoryViewModel(queries)
        viewModel.loadDebt("A", 1)
        advanceUntilIdle()
        assertEquals(listOf("payment-1"), viewModel.state.value.items.map { it.publicId })
        assertEquals("JPY", viewModel.state.value.homeCurrencyCode)
        assertTrue(viewModel.state.value.hasNext)

        viewModel.loadPage(2)
        advanceUntilIdle()
        assertEquals(listOf("payment-2"), viewModel.state.value.items.map { it.publicId })
        assertEquals(2, viewModel.state.value.page)
        assertEquals(2, viewModel.state.value.total)
        assertTrue(viewModel.state.value.hasPrevious)
        assertFalse(viewModel.state.value.hasNext)
    }

    @Test
    fun failedNextPageKeepsVisibleRecordsAndCanRetryRequestedPage() = runTest(dispatcher) {
        var failed = true
        val queries = DebtRepaymentQueries { id, page ->
            if (page == 2 && failed) Result.failure(IOException("offline"))
            else Result.success(historyPage(id, page))
        }
        val viewModel = DebtRepaymentHistoryViewModel(queries)
        viewModel.loadDebt("A", 1)
        advanceUntilIdle()
        viewModel.loadPage(2)
        advanceUntilIdle()
        assertNotNull(viewModel.state.value.error)
        assertEquals(listOf("payment-1"), viewModel.state.value.items.map { it.publicId })
        assertFalse(viewModel.state.value.isLoading)

        failed = false
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(listOf("payment-2"), viewModel.state.value.items.map { it.publicId })
    }

    @Test
    fun canonicalParentVersionChangeReloadsHistoryAndKeepsVoidedFactVisible() = runTest(dispatcher) {
        var page = historyPage("A", 1)
        val viewModel = DebtRepaymentHistoryViewModel(DebtRepaymentQueries { _, _ -> Result.success(page) })
        viewModel.loadDebt("A", 1)
        advanceUntilIdle()

        page = page.copy(items = listOf(page.items.single().copy(
            status = "voided", voidFact = DebtRepaymentVoid("void-1", "重复记录", "2026-09-03T09:00:00Z"),
        )))
        viewModel.loadDebt("A", 2)
        advanceUntilIdle()
        assertEquals("payment-1", viewModel.state.value.items.single().publicId)
        assertEquals("重复记录", viewModel.state.value.items.single().voidFact?.reason)
        assertFalse(viewModel.state.value.items.single().isActive)
    }

    @Test
    fun movingToAnotherDebtDoesNotPublishAnEarlierInFlightHistory() = runTest(dispatcher) {
        val oldLoad = CompletableDeferred<Result<DebtRepaymentPage>>()
        val queries = DebtRepaymentQueries { id, page ->
            if (id == "A") oldLoad.await() else Result.success(historyPage(id, page))
        }
        val viewModel = DebtRepaymentHistoryViewModel(queries)
        viewModel.loadDebt("A", 1)
        runCurrent()
        viewModel.loadDebt("B", 1)
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debtPublicId)

        oldLoad.complete(Result.success(historyPage("A", 1)))
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debtPublicId)
        assertFalse(viewModel.state.value.isLoading)
    }
}

private fun historyPage(id: String, page: Int) = DebtRepaymentPage(
    debtPublicId = id, homeCurrencyCode = "JPY",
    items = listOf(DebtRepayment(
        publicId = "payment-$page", amountCents = 1200L,
        paidAt = "2026-09-01T09:00:00Z", createdAt = "2026-09-01T09:01:00Z", status = "active",
    )),
    page = page, pageSize = 1, total = 2,
)
