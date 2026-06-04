package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice D-1: [AcknowledgeItemsMismatchDispatcher] replay contract.
 *
 * Mirrors [PatchExpenseDispatcherTest]: replays the row's intent-time key,
 * routes ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` ->
 * Conflict, fails loud on a keyless row. The response is an items payload whose
 * wrapper carries the parent expense's bumped ``row_version`` (the stub returns
 * 1L), surfaced as ``Success.newRowVersion`` for the same-target cascade.
 */
internal class AcknowledgeItemsMismatchDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {

    private fun ackRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.AcknowledgeItemsMismatch,
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

    private fun dispatcherFor(stub: ApiServiceStub) = AcknowledgeItemsMismatchDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseStateTokenRequest::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the parent row_version`() = runTest {
        // acknowledgeException = null → the stub returns an items response with
        // parent rowVersion=1L.
        val stub = ApiServiceStub()

        val result = dispatcherFor(stub).dispatch(ackRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastAcknowledgeIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 1L), result)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = ApiServiceStub()

        val result = dispatcherFor(stub).dispatch(ackRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = ApiServiceStub(acknowledgeException = httpException(409, body))

        val result = dispatcherFor(stub).dispatch(ackRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = ApiServiceStub(acknowledgeException = httpException(409, body))

        val result = dispatcherFor(stub).dispatch(ackRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }
}
