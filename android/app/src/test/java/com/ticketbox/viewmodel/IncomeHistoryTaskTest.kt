package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.IncomeDefinition
import com.ticketbox.domain.model.IncomeHistoryPage
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.domain.model.IncomeRevision
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withContext
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomeHistoryTaskTest {
    private val binding = LogicalSessionBinding("https://income.example", "household", "owner", "session", "revision")

    @Test fun failedPageCanRetrySameCursorWithoutLosingOrRepeatingEarlierDefinitions() = runTest {
        val cursors = mutableListOf<Long?>()
        var response = Result.success(page(4, 4))
        var state = IncomeHistoryState()
        val task = IncomeHistoryTask({ captured, id, before ->
            assertEquals(binding, captured)
            assertEquals("income", id)
            cursors += before
            response
        }, backgroundScope, { binding }, { state = it })
        task.open("income")
        runCurrent()
        response = Result.failure(IOException("offline"))
        task.more()
        runCurrent()
        assertEquals(listOf(4L), state.items.map { it.rowVersion })
        assertNotNull(state.error)
        response = Result.success(page(3, null))
        task.retry()
        runCurrent()
        assertEquals(listOf(null, 4L, 4L), cursors)
        assertEquals(listOf(4L, 3L), state.items.map { it.rowVersion })
        assertNull(state.error)
        assertNull(state.nextBeforeVersion)
        task.dismiss()
        assertNull(state.publicId)
        assertTrue(state.items.isEmpty())
    }

    @Test fun replacementSessionRejectsLateOriginalResponseEvenWhenTransportCannotCancel() = runTest {
        val pending = CompletableDeferred<Result<ReadSnapshot<IncomeHistoryPage>>>()
        var current = binding
        var state = IncomeHistoryState()
        val task = IncomeHistoryTask({ captured, _, _ ->
            if (captured == binding) withContext(NonCancellable) { pending.await() }
            else Result.success(page(8, null))
        }, backgroundScope, { current }, { state = it })
        task.open("original")
        runCurrent()
        current = binding.copy(bindingRevision = "replacement")
        task.dismiss()
        task.open("replacement")
        runCurrent()
        pending.complete(Result.success(page(4, null)))
        runCurrent()
        assertEquals("replacement", state.publicId)
        assertEquals(listOf(8L), state.items.map { it.rowVersion })
    }

    @Test fun confirmedAccessDenialRemovesPreviouslyReadHistory() = runTest {
        var response = Result.success(page(4, 4))
        var state = IncomeHistoryState()
        val task = IncomeHistoryTask({ _, _, _ -> response }, backgroundScope, { binding }, { state = it })
        task.open("income")
        runCurrent()
        response = Result.failure(RepositoryException("revoked", httpStatusCode = 403))
        task.more()
        runCurrent()
        assertNull(state.publicId)
        assertTrue(state.items.isEmpty())
    }
}

private fun page(version: Long, next: Long?) = ReadSnapshot(IncomeHistoryPage(listOf(IncomeRevision(
    version, "edit", "2026-09-28T10:00:00Z", "2026-09", "2026-09",
    IncomeDefinition("原收入预测", "salary", "monthly", null, 1200, "JPY", 31, "active"),
)), next), "2026-09-28T10:00:00Z", false)
