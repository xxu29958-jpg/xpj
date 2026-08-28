package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ConfirmedExpenseBatchUpdateRequestDto
import com.ticketbox.data.remote.dto.ConfirmedExpenseBatchUpdateResponseDto
import com.ticketbox.domain.model.BatchApplyResult
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * A confirmed batch edit is one server-owned correction command. Android must
 * not revive the retired per-row PATCH/outbox fan-out: the request carries every
 * target's OCC token plus one human reason, and a successful command is followed
 * by an authoritative confirmed-cache refresh.
 */
internal class ExpenseLedgerRepositoryConfirmedBatchTest : ExpensePendingRepositoryOutboxTestBase() {

    @Test
    fun `batch sends one atomic command with every row token then refreshes confirmed facts`() = runTest {
        val events = mutableListOf<String>()
        val delegate = FakeApiService(events = events, confirmedFailuresRemaining = 0)
        val api = BatchApiService(
            delegate = delegate,
            events = events,
            response = ConfirmedExpenseBatchUpdateResponseDto(
                requestedCount = 2,
                updatedCount = 2,
                skippedNotFound = 0,
                skippedNotConfirmed = 0,
            ),
        )
        val repo = buildRepository(api)
        val first = baselineExpense().copy(id = 1L, status = "confirmed", rowVersion = 3L)
        val second = baselineExpense().copy(id = 2L, status = "confirmed", rowVersion = 8L)

        val result = repo.applyConfirmedBatch(
            expenses = listOf(first, second),
            category = "购物",
            tags = null,
            reason = " 月末统一归类 ",
        ).getOrThrow()

        assertEquals(
            BatchApplyResult(
                requested = 2,
                updated = 2,
                skippedNotFound = 0,
                skippedNotConfirmed = 0,
            ),
            result,
        )
        assertEquals(listOf("batch", "syncConfirmed"), events)
        assertEquals(
            ConfirmedExpenseBatchUpdateRequestDto(
                expenseIds = listOf(1L, 2L),
                expectedRowVersionById = mapOf(1L to 3L, 2L to 8L),
                category = "购物",
                tags = null,
                reason = "月末统一归类",
            ),
            api.request,
        )
    }

    @Test
    fun `batch is online-only and never falls back to retired patch outbox`() = runTest {
        val events = mutableListOf<String>()
        val delegate = FakeApiService(events = events, confirmedFailuresRemaining = 0)
        val api = BatchApiService(
            delegate = delegate,
            events = events,
            failure = IOException("offline"),
        )
        val dao = FakePendingMutationDao()
        val repo = buildRepository(
            api = api,
            outbox = testOutboxRepository(dao = dao),
            adapter = moshi().adapter(com.ticketbox.data.remote.dto.ExpenseUpdateRequest::class.java),
        )
        val expense = baselineExpense().copy(status = "confirmed")

        val result = repo.applyConfirmedBatch(
            expenses = listOf(expense),
            category = null,
            tags = "出差",
            reason = "统一补充出差标签",
        )

        assertTrue(result.isFailure)
        assertEquals(listOf("batch"), events)
        assertTrue(dao.rows.isEmpty(), "atomic batch must not enqueue per-row PatchExpense intents")
        assertFalse(events.contains("syncConfirmed"), "a failed command must not publish a refreshed projection")
    }

    private class BatchApiService(
        private val delegate: ApiService,
        private val events: MutableList<String>,
        private val response: ConfirmedExpenseBatchUpdateResponseDto? = null,
        private val failure: Throwable? = null,
    ) : ApiService by delegate {
        var request: ConfirmedExpenseBatchUpdateRequestDto? = null
            private set

        override suspend fun updateConfirmedBatch(
            request: ConfirmedExpenseBatchUpdateRequestDto,
        ): ConfirmedExpenseBatchUpdateResponseDto {
            events += "batch"
            this.request = request
            failure?.let { throw it }
            return requireNotNull(response)
        }
    }
}
