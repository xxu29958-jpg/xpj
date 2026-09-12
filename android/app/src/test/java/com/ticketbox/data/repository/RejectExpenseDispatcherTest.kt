package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.ApiService
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice D-1: [RejectExpenseDispatcher] replay contract.
 *
 * Mirrors [PatchExpenseDispatcherTest] / [ConfirmExpenseDispatcherTest]:
 * replays the row's intent-time key, routes ``idempotency_key_in_progress`` ->
 * RETRY, keeps ``state_conflict`` -> Conflict, fails loud on a keyless row.
 */
internal class RejectExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {

    private fun rejectRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.RejectExpense,
        targetId = "expense:42",
        payloadJson = moshi().adapter(ExpenseStateTokenRequest::class.java)
            .toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L)),
        expectedRowVersion = 1L,
        status = PendingMutationStatus.InFlight,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-05-20T12:00:00.000Z",
        attemptedAt = "2026-05-20T12:00:00.000Z",
        completedAt = null,
        idempotencyKey = idempotencyKey,
    )

    private fun dispatcherFor(
        stub: ApiService,
        publishExpense: suspend (String, ExpenseDto) -> Unit = { _, _ -> },
    ) = RejectExpenseDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseStateTokenRequest::class.java),
        publishExpense = publishExpense,
    )

    @Test
    fun `accepted reject retains its receipt when cache publication fails`() = runTest {
        val response = successExpenseDto().copy(status = "rejected")
        val stub = ApiServiceStub(rejectExpenseResult = ApiResult.Success(response))
        val row = rejectRow(idempotencyKey = "cache-failure-key")
        val api = object : ApiService by stub {
            override suspend fun rejectExpense(
                id: String,
                request: ExpenseStateTokenRequest,
                idempotencyKey: String?,
            ): ExpenseDto {
                assertEquals("42", id)
                assertEquals(ExpenseStateTokenRequest(expectedRowVersion = row.expectedRowVersion), request)
                return stub.rejectExpense(id, request, idempotencyKey)
            }
        }
        var publicationAttempts = 0
        val result = dispatcherFor(api) { ledgerId, expense ->
            assertEquals(row.ledgerId, ledgerId)
            assertEquals(response, expense)
            publicationAttempts++
            throw IllegalStateException("cache unavailable")
        }.dispatch(row)

        assertEquals(row.idempotencyKey, stub.lastRejectIdempotencyKey)
        assertEquals(1, publicationAttempts)
        assertEquals(DispatchResult.Success(newRowVersion = 2L, cacheRefreshVersion = 2L), result)
    }

    @Test
    fun `dispatch replays the row's idempotency key and returns the new row_version`() = runTest {
        val published = mutableListOf<Pair<String, ExpenseDto>>()
        val stub = ApiServiceStub(rejectExpenseResult = ApiResult.Success(successExpenseDto().copy(status = "rejected")))

        val result = dispatcherFor(stub) { ledgerId, expense ->
            published += ledgerId to expense
        }.dispatch(rejectRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastRejectIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
        assertEquals(listOf("owner" to successExpenseDto().copy(status = "rejected")), published)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = ApiServiceStub(rejectExpenseResult = ApiResult.Success(successExpenseDto()))

        val result = dispatcherFor(stub).dispatch(rejectRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = ApiServiceStub(rejectExpenseResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(rejectRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = ApiServiceStub(rejectExpenseResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(rejectRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }
}
