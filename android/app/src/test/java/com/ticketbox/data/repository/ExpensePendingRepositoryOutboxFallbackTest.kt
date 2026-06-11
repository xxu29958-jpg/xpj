package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0038 PR-2g.3 contract tests (round-8).
 *
 * Two semantic boundaries enforced:
 *
 * 1. ``saveExpenseAllowingOffline`` (used by
 *    ExpenseEditViewModel.save — no chained mutation looks at the
 *    returned token):
 *    - direct 2xx → SaveOutcome.Synced(server expense). No row enqueued.
 *    - IOException → SaveOutcome.Queued(optimistic expense). Row enqueued.
 *    - HttpException (409 / 422 / 500 / etc.) → Result.failure. No row enqueued.
 *
 * 2. ``updateExpense`` (used by confirm / saveAndConfirm chains —
 *    hands ``saved.updatedAt`` to a follow-up POST):
 *    - direct 2xx → Result.success(server expense). No row enqueued.
 *    - IOException → Result.failure. No row enqueued. Chain aborts.
 *    - HttpException → Result.failure. No row enqueued.
 *
 * Shared setup/fixtures live in [ExpensePendingRepositoryOutboxTestBase];
 * sibling state-action, items-editor and outbox-queue cases live in
 * [ExpensePendingRepositoryOutboxStateActionsTest] and
 * [ExpensePendingRepositoryOutboxItemsAndQueueTest].
 */
internal class ExpensePendingRepositoryOutboxFallbackTest : ExpensePendingRepositoryOutboxTestBase() {

    // region — saveExpenseAllowingOffline

    @Test
    fun `save with unresolved queued mutation enqueues behind it, direct PATCH not attempted`() = runTest {
        // Per-target FIFO guard (codex review P1): an unresolved queued
        // mutation (here: an offline confirm) must replay before any later
        // mutation on the same expense — a direct PATCH now would jump it.
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        // Direct PATCH WOULD succeed if attempted — only the guard may divert.
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, adapter)
        outbox.enqueue(
            type = PendingMutationType.ConfirmExpense,
            targetId = "expense:${baseline.id}",
            payloadJson = "{}",
            expectedRowVersion = baseline.rowVersion,
            idempotencyKey = "queued-confirm-key",
        )

        val outcome = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)
            .getOrThrow() as SaveOutcome.Queued

        // Queued surfaces the optimistic projection of the user's edit.
        assertEquals("新商家", outcome.expense.merchant)
        assertNull(
            api.lastIdempotencyKey,
            "direct PATCH must NOT be attempted while a same-target row is queued",
        )
        assertEquals(2, dao.rows.size)
        val rows = dao.rows.values.sortedBy { it.id }
        assertEquals(PendingMutationType.ConfirmExpense.wireValue, rows[0].type)
        assertEquals(PendingMutationType.PatchExpense.wireValue, rows[1].type)
        assertEquals(baseline.rowVersion, rows[1].expectedRowVersion)
        assertNotNull(rows[1].idempotencyKey, "guarded enqueue still carries an intent-time key")
    }

    @Test
    fun `direct 2xx returns Synced with server expense, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)

        val outcome = result.getOrThrow() as SaveOutcome.Synced
        // Server-confirmed: token is the post-PATCH server one, not
        // the pre-mutation baseline.
        assertNotEquals(baseline.updatedAt, outcome.expense.updatedAt)
        assertNotEquals(baseline.rowVersion, outcome.expense.rowVersion)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
        // ADR-0042: the direct PATCH carried an intent-time idempotency key.
        assertNotNull(api.lastIdempotencyKey, "direct PATCH must send an Idempotency-Key")
    }

    @Test
    fun `IOException returns Queued with optimistic expense + enqueues row`() = runTest {
        // codex round-8 P2: queued state surfaces the user's edits
        // (new merchant) on the returned Expense, NOT the
        // pre-edit baseline. Also: payload omits the token (P3#5
        // single source of truth — row.expectedRowVersion is
        // authoritative).
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        val outcome = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)
            .getOrThrow() as SaveOutcome.Queued

        // Optimistic projection: user's new merchant is visible.
        assertEquals("新商家", outcome.expense.merchant)
        // updatedAt stays at baseline (server hasn't confirmed):
        // chained callers should never reach here, but documenting
        // the invariant.
        assertEquals(baseline.updatedAt, outcome.expense.updatedAt)

        // Row enqueued.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.PatchExpense.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertTrue("新商家" in row.payload, "payload must carry the edit: ${row.payload}")
        // codex round-8 P3#5: payload MUST NOT contain the token;
        // single source of truth is row.expectedRowVersion. Replay
        // (PatchExpenseDispatcher) overwrites the request token
        // from the row before dispatching.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token (single source of truth): ${row.payload}",
        )
        // ADR-0042: the enqueued row carries the SAME intent-time key the direct
        // attempt used — that's what lets a committed-but-unseen replay HIT the
        // server's recorded success instead of false-409ing on the stale token.
        assertNotNull(row.idempotencyKey, "PatchExpense row must carry an idempotency key")
        assertEquals(api.lastIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(409, """{"error":"state_conflict","message":"账单已修改"}""")))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)

        assertTrue(result.isFailure, "409 must surface to user, not silently queue")
        assertEquals(0, dao.rows.size, "409 conflict MUST NOT enqueue")
    }

    @Test
    fun `HttpException 422 surfaces as failure, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(422, """{"error":"invalid_amount"}""")))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)

        assertTrue(result.isFailure, "422 user-input error must surface, not queue")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `HttpException 500 surfaces as failure, no enqueue`() = runTest {
        // 5xx is reachable-server-unhappy, not offline. Outbox
        // replay would just retry the same broken server. Surface
        // to user instead.
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(500, """{"error":"internal"}""")))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)

        assertTrue(result.isFailure, "5xx must surface, not queue (server reachable but unhappy)")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `IOException after ledger switch mid-flight does NOT enqueue`() = runTest {
        // [codex round-13 P1] Race: user taps save under ledger A,
        // request starts, user switches to ledger B (clearAll wipes
        // OLD rows + bumps epoch), then the request throws
        // IOException. Without the post-IOException
        // ``requireStillActive`` check the catch would enqueue a NEW
        // row keyed to ledger A's expenseId into ledger B's queue —
        // worker drains it under B's session → wrong-session replay.
        //
        // The fix in [ExpensePendingRepository.saveExpenseAllowingOffline]
        // calls ``bound.requireStillActive()`` in the IOException
        // catch BEFORE enqueueing; mid-flight switch throws
        // RepositoryException("账本已切换…") which safeCall maps to
        // Result.failure.
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        // Shared settings so the ApiService stub can flip the
        // active ledger from the same store the repository binds
        // against.
        val settings = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "ledger-a",
                ledgerName = "账本 A",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokens = FakeSessionTokenStore().apply { saveToken("session-token") }

        // Stub simulates "switch fired during the call": flip the
        // settings store's active ledger BEFORE throwing IOException.
        val api = object : ApiService by FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ) {
            override suspend fun updateExpense(
                id: Long,
                request: ExpenseUpdateRequest,
                idempotencyKey: String?,
            ): ExpenseDto {
                settings.saveIdentity(
                    accountName = "我",
                    ledgerId = "ledger-b",
                    ledgerName = "账本 B",
                    deviceName = "Pixel",
                    role = "owner",
                    boundAt = "2026-05-04T12:00:00Z",
                )
                throw IOException("net out")
            }
        }

        val repo = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = TestApiServiceFactory(api),
            settingsStore = settings,
            tokenStore = tokens,
            deviceNameProvider = { "Android Test" },
            outbox = outbox,
            patchExpenseAdapter = adapter,
        )

        val result = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)

        assertTrue(
            result.isFailure,
            "mid-flight ledger switch must surface as failure, not silently enqueue under new session",
        )
        assertEquals(
            0,
            dao.rows.size,
            "no row should be enqueued when session changed between bind and IOException",
        )
    }

    @Test
    fun `IOException without outbox wired stays as failure`() = runTest {
        // Pre-PR-2g.3 wiring shape — outbox null. IOException must
        // surface as Result.failure; we don't silently lose the
        // mutation, and the round-9 fix (NetworkErrorHandler routes
        // Log.w through logNetworkWarning) keeps this testable in
        // pure-JVM unit tests.
        val baseline = baselineExpense()
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox = null, adapter = null)

        val result = repo.saveExpenseAllowingOffline(baseline.id, draft, baseline)

        assertTrue(result.isFailure)
    }

    // endregion

    // region — updateExpense (direct only — chained-caller contract)

    @Test
    fun `updateExpense IOException is failure even when outbox wired (chained caller path)`() = runTest {
        // Codex round-7 P1 fix: ``updateExpense`` is used by
        // confirm / saveAndConfirm — they hand ``saved.updatedAt``
        // to a follow-up POST. If we silently queued, the chain
        // would dispatch with a stale token. The CONTRACT is two
        // things: (1) Result MUST be failure so the chain aborts,
        // and (2) no row is enqueued. Both are checked here.
        //
        // The round-9 fix to ``NetworkErrorHandler`` (route Log.w
        // through ``logNetworkWarning`` which catches the android.util.Log
        // stub exception in pure-JVM tests) is what restored
        // testability of assertion (1).
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)

        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.updateExpense(baseline.id, draft, baseline)

        assertTrue(
            result.isFailure,
            "updateExpense MUST surface IOException — chained confirm depends on it aborting",
        )
        assertEquals(
            0,
            dao.rows.size,
            "updateExpense MUST NOT enqueue — chained callers must NOT see a fake 'saved' state",
        )
    }

    // endregion
}
