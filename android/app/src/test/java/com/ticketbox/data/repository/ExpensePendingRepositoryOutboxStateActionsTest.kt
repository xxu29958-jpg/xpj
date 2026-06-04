package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * ADR-0038 PR-2g.7/.8/.9 offline-fallback contract for the
 * state-transition ``*AllowingOffline`` actions:
 * confirm / reject / markNotDuplicate / retryOcr /
 * acknowledgeItemsMismatch.
 *
 * Each enforces the same three-way boundary as the PATCH path
 * ([ExpensePendingRepositoryOutboxFallbackTest]): direct 2xx →
 * Synced (no enqueue), IOException → Queued optimistic projection +
 * token-only row, HttpException → failure (no enqueue). Shared
 * setup lives in [ExpensePendingRepositoryOutboxTestBase].
 */
internal class ExpensePendingRepositoryOutboxStateActionsTest : ExpensePendingRepositoryOutboxTestBase() {

    // region — confirm / reject AllowingOffline (PR-2g.7)

    @Test
    fun `confirm direct 2xx returns Synced with server expense, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(
            confirmExpenseResult = ApiResult.Success(successExpenseDto(serverUpdatedAt = "2026-05-20T14:00:00.000Z")),
        )
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.confirmExpenseAllowingOffline(baseline)
            .getOrThrow() as ExpenseStateOutcome.Synced

        assertNotEquals(baseline.updatedAt, outcome.expense.updatedAt)
        assertNotEquals(baseline.rowVersion, outcome.expense.rowVersion)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }

    @Test
    fun `confirm IOException returns Queued confirmed projection + enqueues token-only row`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(confirmExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.confirmExpenseAllowingOffline(baseline)
            .getOrThrow() as ExpenseStateOutcome.Queued

        // Optimistic projection: status flipped to confirmed; the
        // token stays at baseline (NOT a server-confirmed one).
        assertEquals("confirmed", outcome.expense.status)
        assertEquals(baseline.updatedAt, outcome.expense.updatedAt)

        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.ConfirmExpense.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // round-8 P3#5: token must NOT be embedded in payload — the
        // row's expectedRowVersion is the single source of truth.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token (single source of truth): ${row.payload}",
        )
        // ADR-0042: the enqueued row carries the SAME intent-time key the direct
        // attempt used — that's what lets a committed-but-unseen replay HIT the
        // server's recorded success instead of false-409ing on the stale token.
        assertNotNull(row.idempotencyKey, "ConfirmExpense row must carry an idempotency key")
        assertEquals(api.lastConfirmIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `confirm HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(
            confirmExpenseResult = ApiResult.Throw(
                httpException(409, """{"error":"state_conflict","message":"账单已修改"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val result = repo.confirmExpenseAllowingOffline(baselineExpense())

        assertTrue(result.isFailure, "409 must surface to user, not silently queue")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `confirm IOException without outbox wired stays as failure`() = runTest {
        val api = ApiServiceStub(confirmExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox = null, stateTokenAdapter = null)

        val result = repo.confirmExpenseAllowingOffline(baselineExpense())

        assertTrue(result.isFailure)
    }

    @Test
    fun `reject direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(rejectExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.rejectExpenseAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is ExpenseStateOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `reject IOException returns Queued rejected projection + enqueues row`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(rejectExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.rejectExpenseAllowingOffline(baseline)
            .getOrThrow() as ExpenseStateOutcome.Queued

        assertEquals("rejected", outcome.expense.status)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.RejectExpense.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertNotNull(row.idempotencyKey, "RejectExpense row must carry an idempotency key")
        assertEquals(api.lastRejectIdempotencyKey, row.idempotencyKey)
    }

    // endregion

    // region — markNotDuplicate / retryOcr AllowingOffline (PR-2g.8)

    @Test
    fun `markNotDuplicate IOException returns Queued none-projection + enqueues row`() = runTest {
        val baseline = baselineExpense().copy(duplicateStatus = "suspected")
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(markNotDuplicateResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.markNotDuplicateAllowingOffline(baseline)
            .getOrThrow() as ExpenseStateOutcome.Queued

        // Optimistic projection clears the suspected-duplicate badge.
        assertEquals("none", outcome.expense.duplicateStatus)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.MarkNotDuplicate.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertNotNull(row.idempotencyKey, "MarkNotDuplicate row must carry an idempotency key")
        assertEquals(api.lastMarkNotDuplicateIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `markNotDuplicate direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense().copy(duplicateStatus = "suspected")
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(markNotDuplicateResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.markNotDuplicateAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is ExpenseStateOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `retryOcr IOException returns Queued unchanged + enqueues row`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(retryOcrResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.retryOcrAllowingOffline(baseline)
            .getOrThrow() as ExpenseStateOutcome.Queued

        // No optimistic field change — OCR re-runs server-side, so the
        // queued projection is the expense unchanged.
        assertEquals(baseline.updatedAt, outcome.expense.updatedAt)
        assertEquals(baseline.merchant, outcome.expense.merchant)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.RetryOcr.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertNotNull(row.idempotencyKey, "RetryOcr row must carry an idempotency key")
        assertEquals(api.lastRetryOcrIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `retryOcr direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.retryOcrAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is ExpenseStateOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    // endregion

    // region — acknowledgeItemsMismatch AllowingOffline (PR-2g.9)

    @Test
    fun `acknowledge IOException returns Queued acknowledged-projection + enqueues row`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(acknowledgeException = IOException("net out"))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current)
            .getOrThrow() as ItemsAckOutcome.Queued

        // Optimistic projection flips the items-sum status to acknowledged.
        assertEquals("mismatch_acknowledged", outcome.items.itemsSumStatus)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.AcknowledgeItemsMismatch.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertNotNull(row.idempotencyKey, "AcknowledgeItemsMismatch row must carry an idempotency key")
        assertEquals(api.lastAcknowledgeIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `acknowledge direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        // acknowledgeException = null → success path.
        val api = ApiServiceStub()
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current).getOrThrow()

        assertTrue(outcome is ItemsAckOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `acknowledge HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(
            acknowledgeException = httpException(409, """{"error":"state_conflict","message":"账单已修改"}"""),
        )
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val result = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current)

        assertTrue(result.isFailure, "409 must surface, not silently queue")
        assertEquals(0, dao.rows.size)
    }

    // endregion
}
