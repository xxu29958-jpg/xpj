package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

internal class CorrectExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {
    private fun revision() = ExpenseRevisionDto(
        publicId = "revision-public",
        revisionNumber = 2L,
        changeKind = "correction",
        reason = "金额录错了",
        changedFields = listOf("amount_cents"),
        before = mapOf("amount_cents" to 12345.0),
        after = mapOf("amount_cents" to 15000.0),
        actorAccountName = "我",
        actorDeviceName = "Pixel",
        createdAt = "2026-05-20T13:00:00Z",
    )

    private sealed interface StubResult {
        data class Success(val response: ExpenseCorrectionResponseDto) : StubResult
        data class Throw(val error: Throwable) : StubResult
    }

    private class Stub(
        private val result: StubResult,
    ) : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
        var lastId: String? = null
        var lastRequest: ExpenseCorrectionRequestDto? = null
        var lastKey: String? = null

        override suspend fun correctExpense(
            id: String,
            request: ExpenseCorrectionRequestDto,
            idempotencyKey: String?,
        ): ExpenseCorrectionResponseDto {
            lastId = id
            lastRequest = request
            lastKey = idempotencyKey
            return when (val current = result) {
                is StubResult.Success -> current.response
                is StubResult.Throw -> throw current.error
            }
        }
    }

    private fun row(key: String? = "correction-key") = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.CorrectExpense,
        targetId = "expense:42",
        payloadJson = moshi().adapter(ExpenseCorrectionRequestDto::class.java).toJson(
            ExpenseCorrectionRequestDto(
                expectedRowVersion = 0L,
                reason = "金额录错了",
                amountCents = 15000L,
            ),
        ),
        expectedRowVersion = 7L,
        status = PendingMutationStatus.InFlight,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-05-20T12:00:00Z",
        attemptedAt = "2026-05-20T12:00:00Z",
        completedAt = null,
        idempotencyKey = key,
    )

    @Test
    fun `success reuses key refreshes token and caches authoritative expense`() = runTest {
        val response = ExpenseCorrectionResponseDto(
            expense = successExpenseDto().copy(
                status = "confirmed",
                rowVersion = 8L,
                factRevision = 2L,
            ),
            revision = revision(),
        )
        val stub = Stub(StubResult.Success(response))
        var cached: Pair<String, Long>? = null
        val dispatcher = CorrectExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi().adapter(ExpenseCorrectionRequestDto::class.java),
            cacheAuthoritativeExpense = { ledgerId, dto -> cached = ledgerId to dto.factRevision },
        )

        val result = dispatcher.dispatch(row())

        assertEquals("42", stub.lastId)
        assertEquals("correction-key", stub.lastKey)
        assertEquals(7L, stub.lastRequest?.expectedRowVersion)
        assertEquals("金额录错了", stub.lastRequest?.reason)
        assertEquals("owner" to 2L, cached)
        assertEquals(DispatchResult.Success(newRowVersion = 8L), result)
    }

    @Test
    fun `missing key fails without calling server`() = runTest {
        val stub = Stub(StubResult.Throw(AssertionError("server must not be called")))
        val dispatcher = CorrectExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi().adapter(ExpenseCorrectionRequestDto::class.java),
            cacheAuthoritativeExpense = { _, _ -> },
        )

        assertTrue(dispatcher.dispatch(row(key = null)) is DispatchResult.Failure)
    }

    @Test
    fun `state conflict stays user resolvable`() = runTest {
        val stub = Stub(
            StubResult.Throw(
                httpException(
                    409,
                    """{"error":"state_conflict","message":"账单已被其它端修改"}""",
                ),
            ),
        )
        val dispatcher = CorrectExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi().adapter(ExpenseCorrectionRequestDto::class.java),
            cacheAuthoritativeExpense = { _, _ -> },
        )

        assertTrue(dispatcher.dispatch(row()) is DispatchResult.Conflict)
    }
}
