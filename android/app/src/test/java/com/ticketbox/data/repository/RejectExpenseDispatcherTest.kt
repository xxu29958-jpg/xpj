package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
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
        stub: ApiServiceStub,
        deleteConfirmedCache: suspend (String, List<Long>) -> Unit = { _, _ -> },
    ) = RejectExpenseDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseStateTokenRequest::class.java),
        deleteConfirmedCache = deleteConfirmedCache,
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the new row_version`() = runTest {
        val deleted = mutableListOf<Pair<String, List<Long>>>()
        val stub = ApiServiceStub(rejectExpenseResult = ApiResult.Success(successExpenseDto().copy(status = "rejected")))

        val result = dispatcherFor(stub) { ledgerId, serverIds ->
            deleted += ledgerId to serverIds
        }.dispatch(rejectRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastRejectIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
        assertEquals(listOf("owner" to listOf(42L)), deleted)
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
