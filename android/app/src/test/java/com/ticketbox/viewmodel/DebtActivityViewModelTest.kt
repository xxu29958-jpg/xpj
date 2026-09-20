package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActivityQueries
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.DebtActivityPage
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
class DebtActivityViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun acknowledgedProposalInvalidatesActivityWithoutChangingDebtVersion() = runTest(dispatcher) {
        var reads = 0
        val model = DebtActivityViewModel(DebtActivityQueries { task, page, _ ->
            reads++
            Result.success(historyPage(task.debtPublicId, page))
        })
        val task = memberDebtTask("A")
        model.loadDebt(task, 1)
        advanceUntilIdle()
        model.loadDebt(task, 1, acknowledgedCommandRevision = 1)
        advanceUntilIdle()
        assertEquals(2, reads)
        model.loadDebt(task, 1, acknowledgedCommandRevision = 1)
        advanceUntilIdle()
        assertEquals(2, reads)
    }

    @Test
    fun failedReentryKeepsTheRetainedPageAndRetriesTheCurrentTimeline() = runTest(dispatcher) {
        var fail = false
        val requestedPages = mutableListOf<Int>()
        val model = DebtActivityViewModel(DebtActivityQueries { task, page, _ ->
            requestedPages += page
            if (fail) Result.failure(IOException("offline")) else Result.success(historyPage(task.debtPublicId, page))
        })
        val task = memberDebtTask("A")
        model.loadDebt(task, 1)
        advanceUntilIdle()
        model.loadPage(2)
        advanceUntilIdle()
        fail = true
        model.loadDebt(task, 1, forceRefresh = true)
        advanceUntilIdle()
        assertEquals("payment-2", model.state.value.items.single().publicId)
        assertEquals(2, model.state.value.page)
        assertNotNull(model.state.value.error)
        fail = false
        model.refresh()
        advanceUntilIdle()
        assertEquals(listOf(1, 2, 1, 1), requestedPages)
        assertEquals("payment-1", model.state.value.items.single().publicId)
        assertEquals(null, model.state.value.error)
    }

    @Test
    fun acceptedCommandRefreshFailureMakesRetainedPageReadOnlyUntilRecovery() = runTest(dispatcher) {
        var fail = false
        val model = DebtActivityViewModel(DebtActivityQueries { task, page, _ ->
            if (fail) Result.failure(IOException("offline")) else Result.success(historyPage(task.debtPublicId, page))
        })
        val task = memberDebtTask("A")
        model.loadDebt(task, 1)
        advanceUntilIdle()
        model.loadPage(2)
        advanceUntilIdle()
        assertTrue(model.state.value.actionsCurrent)
        fail = true
        model.loadDebt(task, 1, acknowledgedCommandRevision = 1)
        advanceUntilIdle()
        assertEquals("payment-2", model.state.value.items.single().publicId)
        assertEquals(2, model.state.value.page)
        assertNotNull(model.state.value.error)
        assertFalse(model.state.value.actionsCurrent)
        fail = false
        model.refresh()
        advanceUntilIdle()
        assertTrue(model.state.value.actionsCurrent)
        assertEquals("payment-1", model.state.value.items.single().publicId)
        assertEquals(null, model.state.value.error)
    }

    @Test
    fun linkedPaymentUsesServerPageAndFailedFocusCanRetryWithoutLosingCurrentRows() = runTest(dispatcher) {
        var fail = true
        val focuses = mutableListOf<String?>()
        val model = DebtActivityViewModel(DebtActivityQueries { task, page, focus ->
            focuses += focus
            if (focus != null && fail) Result.failure(IOException("offline"))
            else Result.success(historyPage(task.debtPublicId, if (focus == null) page else 3).copy(total = 3))
        })
        model.loadDebt(memberDebtTask("A"), 1)
        advanceUntilIdle()
        model.openRepayment("payment-3")
        advanceUntilIdle()
        assertEquals("payment-1", model.state.value.items.single().publicId)
        assertNotNull(model.state.value.error)
        fail = false
        model.refresh()
        advanceUntilIdle()
        assertEquals(3, model.state.value.page)
        assertEquals("payment-3", model.state.value.items.single().publicId)
        assertEquals("payment-3", model.state.value.focusedRepaymentId)
        assertEquals(listOf(null, "payment-3", "payment-3"), focuses)
        model.refresh()
        advanceUntilIdle()
        assertEquals(3, model.state.value.page)
        assertEquals(null, focuses.last())
    }

    @Test
    fun pageNavigationReplacesRatherThanMergesIndependentResponses() = runTest(dispatcher) {
        val queries = DebtActivityQueries { id, page, _ -> Result.success(historyPage(id.debtPublicId, page)) }
        val viewModel = DebtActivityViewModel(queries)
        viewModel.loadDebt(memberDebtTask("A"), 1)
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
        val queries = DebtActivityQueries { id, page, _ ->
            if (page == 2 && failed) Result.failure(IOException("offline"))
            else Result.success(historyPage(id.debtPublicId, page))
        }
        val viewModel = DebtActivityViewModel(queries)
        viewModel.loadDebt(memberDebtTask("A"), 1)
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
        val viewModel = DebtActivityViewModel(DebtActivityQueries { _, _, _ -> Result.success(page) })
        viewModel.loadDebt(memberDebtTask("A"), 1)
        advanceUntilIdle()

        page = page.copy(items = listOf(page.items.single().copy(
            repayment = page.items.single().repayment?.copy(
                status = "voided", voidFact = DebtRepaymentVoid("void-1", "重复记录", "2026-09-03T09:00:00Z")),
        )))
        viewModel.loadDebt(memberDebtTask("A"), 2)
        advanceUntilIdle()
        assertEquals("payment-1", viewModel.state.value.items.single().publicId)
        assertEquals("重复记录", viewModel.state.value.items.single().repayment?.voidFact?.reason)
        assertFalse(viewModel.state.value.items.single().repayment?.isActive == true)
    }

    @Test
    fun movingToAnotherDebtDoesNotPublishAnEarlierInFlightHistory() = runTest(dispatcher) {
        val oldLoad = CompletableDeferred<Result<DebtActivityPage>>()
        val queries = DebtActivityQueries { id, page, _ ->
            if (id.debtPublicId == "A") oldLoad.await() else Result.success(historyPage(id.debtPublicId, page))
        }
        val viewModel = DebtActivityViewModel(queries)
        viewModel.loadDebt(memberDebtTask("A"), 1)
        runCurrent()
        viewModel.loadDebt(memberDebtTask("B"), 1)
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debtPublicId)

        oldLoad.complete(Result.success(historyPage("A", 1)))
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debtPublicId)
        assertFalse(viewModel.state.value.isLoading)
    }
    @Test
    fun sameDebtAndVersionUnderAnotherBindingCannotReuseEarlierHistory() = runTest(dispatcher) {
        val original = memberDebtTask("A")
        val replacement = original.copy(binding = original.binding.copy(bindingRevision = "replacement"))
        val oldLoad = CompletableDeferred<Result<DebtActivityPage>>()
        val queries = DebtActivityQueries { task, page, _ ->
            if (task == original) oldLoad.await() else Result.success(historyPage(task.debtPublicId, page)
                .copy(items = emptyList(), total = 0))
        }
        val model = DebtActivityViewModel(queries)
        model.loadDebt(original, 1)
        runCurrent()
        model.loadDebt(replacement, 1)
        advanceUntilIdle()
        oldLoad.complete(Result.success(historyPage("A", 1)))
        advanceUntilIdle()
        assertEquals(replacement.binding, model.state.value.binding)
        assertTrue(model.state.value.items.isEmpty())
        model.loadDebt(null, 0)
        assertEquals(null, model.state.value.debtPublicId)
    }

    @Test
    fun failedInitialHistoryKeepsItsRenderedTaskAndRetryFeedback() = runTest(dispatcher) {
        val task = memberDebtTask("A")
        val model = DebtActivityViewModel(DebtActivityQueries { _, _, _ -> Result.failure(IOException("offline")) })
        model.loadDebt(task, 1)
        assertTrue(model.state.value.isLoading)
        assertEquals(task.binding, model.state.value.binding)
        advanceUntilIdle()
        assertEquals("A", model.state.value.debtPublicId)
        assertEquals(task.binding, model.state.value.binding)
        assertNotNull(model.state.value.error)
        assertFalse(model.state.value.isLoading)
    }

}

private fun historyPage(id: String, page: Int) = DebtActivityPage(
    debtPublicId = id, homeCurrencyCode = "JPY",
    items = listOf(DebtActivity(kind = "repayment", publicId = "payment-$page", recordedAt = "2026-09-01T09:01:00Z",
        actorDisplayName = null, actorIsYou = false, repayment = DebtRepayment(
        publicId = "payment-$page", amountCents = 1200L,
        paidAt = "2026-09-01T09:00:00Z", createdAt = "2026-09-01T09:01:00Z", status = "active",
    ))),
    page = page, pageSize = 1, total = 2,
)
