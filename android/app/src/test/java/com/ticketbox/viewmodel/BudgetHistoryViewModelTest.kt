package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BudgetHistoryReader
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetArrangement
import com.ticketbox.domain.model.BudgetHistoryPage
import com.ticketbox.domain.model.BudgetRevision
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

@OptIn(ExperimentalCoroutinesApi::class)
class BudgetHistoryViewModelTest {
    private fun historyTest(block: suspend TestScope.() -> Unit) = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try { block() } finally { advanceUntilIdle(); Dispatchers.resetMain() }
    }

    @Test fun pagingRetriesKeepReadableArrangementsWhileRefusalClearsThem() = historyTest {
        val reader = HistoryReader()
        val vm = BudgetHistoryViewModel(reader)
        runCurrent()
        vm.open("2026-09")
        advanceUntilIdle()
        assertEquals(listOf(2L), vm.state.value.items.map { it.rowVersion })
        reader.result = Result.failure(IOException("offline"))
        vm.next()
        advanceUntilIdle()
        assertTrue(vm.state.value.failed)
        assertEquals(listOf(2L), vm.state.value.items.map { it.rowVersion })
        reader.result = Result.success(historyPage(1, null))
        vm.retry()
        advanceUntilIdle()
        assertEquals(listOf(2L, 1L), vm.state.value.items.map { it.rowVersion })
        assertEquals(listOf(null, 2L, 2L), reader.cursors)
        reader.result = Result.failure(RepositoryException("permission_denied", httpStatusCode = 403))
        vm.open("2026-09")
        advanceUntilIdle()
        assertTrue(vm.state.value.failed)
        assertTrue(vm.state.value.items.isEmpty())
    }

    @Test fun replacingSameNamedLedgerRejectsTheOldPendingReadAndStartsFromTheNewBinding() = historyTest {
        val reader = HistoryReader()
        val oldRead = CompletableDeferred<Result<BudgetHistoryPage>>()
        reader.pending = oldRead
        val vm = BudgetHistoryViewModel(reader)
        runCurrent()
        vm.open("2026-09")
        runCurrent()
        val replacement = requireNotNull(reader.access.value).binding.copy(ownerKey = "replacement-owner")
        reader.pending = null
        reader.result = Result.success(historyPage(1, null))
        reader.access.value = LedgerAccessContext(replacement, canModify = false)
        runCurrent()
        oldRead.complete(Result.success(historyPage(2, 2)))
        advanceUntilIdle()
        assertEquals(listOf(1L), vm.state.value.items.map { it.rowVersion })
        assertEquals(replacement, reader.bindings.last())
        reader.access.value = null
        advanceUntilIdle()
        assertTrue(vm.state.value.items.isEmpty())
    }
}

private class HistoryReader : BudgetHistoryReader {
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(
        LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "binding"), true))
    var result = Result.success(historyPage(2, 2))
    var pending: CompletableDeferred<Result<BudgetHistoryPage>>? = null
    val cursors = mutableListOf<Long?>()
    val bindings = mutableListOf<LogicalSessionBinding>()
    override fun observeActiveLedgerAccess() = access
    override suspend fun history(binding: LogicalSessionBinding, month: String, beforeVersion: Long?): Result<BudgetHistoryPage> {
        cursors += beforeVersion
        bindings += binding
        return pending?.await() ?: result
    }
}

private fun historyPage(version: Long, next: Long?) = BudgetHistoryPage("ledger", "2026-09",
    listOf(BudgetRevision(version, "edit", "2026-09-26T00:00:00Z",
        BudgetArrangement("JPY", 1200, 100, -20, listOf("旅行"), emptyList(), false))), next)
