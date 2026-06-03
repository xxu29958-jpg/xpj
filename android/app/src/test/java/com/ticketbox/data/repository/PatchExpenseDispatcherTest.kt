package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice B: [PatchExpenseDispatcher] replay contract.
 *
 * Pins the idempotency-key half of the offline round-trip: the dispatcher must
 * replay the row's intent-time key as the ``Idempotency-Key`` header (so a
 * committed-but-unseen first attempt is deduped server-side → HIT → canonical
 * row, not a false 409), and it must route the new ``idempotency_key_in_progress``
 * 409 to RETRY (a concurrent same-key claim is still mid-flight and will land)
 * rather than dropping the row. Reuses the ``ExpensePendingRepositoryOutbox``
 * fixtures (``ApiServiceStub`` captures the key; ``successExpenseDto`` /
 * ``httpException`` build the responses) instead of re-deriving the heavyweight
 * ``ExpenseDto`` shape here.
 */
internal class PatchExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {

    private fun patchRow(idempotencyKey: String?): OutboxRow {
        val payload = moshi().adapter(ExpenseUpdateRequest::class.java)
            .toJson(draft.toRequest(baseline = baselineExpense()).copy(expectedRowVersion = null))
        return OutboxRow(
            id = 1L,
            serverUrl = "https://api.example.com",
            ledgerId = "owner",
            type = PendingMutationType.PatchExpense,
            targetId = "expense:42",
            payloadJson = payload,
            expectedRowVersion = 1L,
            status = PendingMutationStatus.InFlight,
            retryCount = 0,
            lastError = null,
            createdAt = "2026-05-20T12:00:00.000Z",
            attemptedAt = "2026-05-20T12:00:00.000Z",
            completedAt = null,
            idempotencyKey = idempotencyKey,
        )
    }

    private fun dispatcherFor(stub: ApiServiceStub) = PatchExpenseDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseUpdateRequest::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the new row_version`() = runTest {
        val stub = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))

        val result = dispatcherFor(stub).dispatch(patchRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        // successExpenseDto carries rowVersion=2L → cascaded to same-target rows.
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        // Pre-ADR-0042 rows (null key) can't be replayed safely. The guard must
        // surface a visible FAILED row (user can drop it) rather than send a
        // null header → server 422 → silent Discard. A Success here would mean
        // the guard didn't fire.
        val stub = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))

        val result = dispatcherFor(stub).dispatch(patchRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        // A concurrent same-key request is still mid-flight; the replay will HIT
        // once it commits, so the row must stay PENDING and retry.
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(patchRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        // Regression guard: the in_progress branch must not swallow the genuine
        // OCC conflict that drives the keep-mine / drop-mine banner.
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(patchRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun `422 idempotency_key_reused is discarded, not retried forever`() = runTest {
        // Same key, different request — terminal (a UUID never legitimately
        // collides). Drop the structurally-broken row rather than loop on it.
        val body = """{"error":"idempotency_key_reused","message":"幂等键已被另一请求使用，请勿复用。"}"""
        val stub = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(422, body)))

        val result = dispatcherFor(stub).dispatch(patchRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Discarded, "reused (422) must Discard: $result")
    }
}
