package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
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
 * Plus round-7 P2 + round-8 P2 sanity: [OutboxRepository.enqueue]'s
 * onEnqueued callback is best-effort; throwing it doesn't make
 * enqueue itself fail (the row is already committed before the
 * callback fires).
 */
class ExpensePendingRepositoryOutboxFallbackTest {

    private fun baselineExpense(updatedAt: String = "2026-05-20T12:00:05.000Z"): Expense = Expense(
        id = 42L,
        publicId = "test-public-id",
        amountCents = 12345L,
        merchant = "原商家",
        category = "餐饮",
        note = "",
        source = "Android截图",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "pending",
        expenseTime = "2026-05-20T12:00:00Z",
        createdAt = "2026-05-20T12:00:00Z",
        updatedAt = updatedAt,
        confirmedAt = null,
        rejectedAt = null,
    )

    private val draft = ExpenseDraft(
        amountCents = 12345L,
        originalAmountMinor = 12345L,
        originalCurrencyCode = CurrencyCode.CNY,
        merchant = "新商家",
        category = "餐饮",
        note = "",
        expenseTime = "2026-05-20T12:00:00Z",
        tags = null,
        valueScore = null,
        regretScore = null,
    )

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun seededSettingsStore(): FakeTicketboxSettingsStore =
        FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }

    private fun seededTokenStore(): FakeSessionTokenStore =
        FakeSessionTokenStore().apply { saveToken("session-token") }

    private class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private fun buildRepository(
        api: ApiService,
        outbox: OutboxRepository? = null,
        adapter: com.squareup.moshi.JsonAdapter<ExpenseUpdateRequest>? = null,
        stateTokenAdapter: com.squareup.moshi.JsonAdapter<ExpenseStateTokenRequest>? = null,
    ): ExpenseRepository = ExpenseRepository(
        expenseDao = FakeExpenseDao(),
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        deviceNameProvider = { "Android Test" },
        outbox = outbox,
        patchExpenseAdapter = adapter,
        expenseStateTokenAdapter = stateTokenAdapter,
    )

    private fun successExpenseDto(serverUpdatedAt: String = "2026-05-20T13:00:00.000Z"): ExpenseDto =
        ExpenseDto(
            id = 42L,
            publicId = "test-public-id",
            amountCents = 12345L,
            merchant = "新商家",
            category = "餐饮",
            note = "",
            source = "Android截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "pending",
            expenseTime = "2026-05-20T12:00:00Z",
            createdAt = "2026-05-20T12:00:00Z",
            updatedAt = serverUpdatedAt,
            confirmedAt = null,
            rejectedAt = null,
        )

    // region — saveExpenseAllowingOffline

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
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }

    @Test
    fun `IOException returns Queued with optimistic expense + enqueues row`() = runTest {
        // codex round-8 P2: queued state surfaces the user's edits
        // (new merchant) on the returned Expense, NOT the
        // pre-edit baseline. Also: payload omits the token (P3#5
        // single source of truth — row.expectedUpdatedAt is
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
        assertEquals(baseline.updatedAt, row.expectedUpdatedAt)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertTrue("新商家" in row.payload, "payload must carry the edit: ${row.payload}")
        // codex round-8 P3#5: payload MUST NOT contain the token;
        // single source of truth is row.expectedUpdatedAt. Replay
        // (PatchExpenseDispatcher) overwrites the request token
        // from the row before dispatching.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token (single source of truth): ${row.payload}",
        )
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
        assertEquals(baseline.updatedAt, row.expectedUpdatedAt)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // round-8 P3#5: token must NOT be embedded in payload — the
        // row's expectedUpdatedAt is the single source of truth.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token (single source of truth): ${row.payload}",
        )
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
        assertEquals(baseline.updatedAt, row.expectedUpdatedAt)
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token: ${row.payload}",
        )
    }

    // endregion

    // region — OutboxRepository invariants (round-7 P2 + round-8)

    @Test
    fun `OutboxRepository enqueue does not fail when onEnqueued throws`() = runTest {
        // Codex round-7 P2: onEnqueued is a best-effort scheduler
        // wake. If WorkManager throws, the row is already in the
        // DAO and periodic worker will pick it up. Round-8 P2
        // narrowed the catch from Throwable to Exception so
        // JVM-level Errors propagate.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(
            dao = dao,
            onEnqueued = { throw IllegalStateException("simulated WorkManager fault") },
        )

        val rowId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:42",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-20T12:00:05.000Z",
        )

        assertTrue(rowId > 0)
        assertEquals(1, dao.rows.size)
    }

    @Test
    fun `clearAll drops every row and fires onClearAll`() = runTest {
        // codex round-8 P1: session-boundary lifecycle hook.
        // clearAll must (a) wipe the DAO and (b) signal the
        // scheduler-cancel callback.
        val dao = FakePendingMutationDao()
        var cancelled = false
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = { cancelled = true },
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-20T12:00:00.000Z",
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-20T12:00:01.000Z",
        )

        val removed = outbox.clearAll()

        assertEquals(2, removed, "all rows reported as removed")
        assertEquals(0, dao.rows.size, "DAO is empty after clearAll")
        assertTrue(cancelled, "onClearAll must fire (scheduler-cancel signal)")
    }

    @Test
    fun `clearAll still succeeds when onClearAll throws (best-effort callback)`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = { throw IllegalStateException("simulated WorkManager.cancel fault") },
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-20T12:00:00.000Z",
        )

        val removed = outbox.clearAll()

        assertEquals(1, removed)
        assertEquals(0, dao.rows.size)
    }

    // endregion

    private sealed interface ApiResult {
        data class Success(val dto: ExpenseDto) : ApiResult
        data class Throw(val exception: Throwable) : ApiResult
    }

    /**
     * Minimal ApiService stand-in: every method falls through to a
     * delegate that throws (via FakeApiService), but ``updateExpense``
     * is configurable per test (return a DTO or throw).
     */
    private class ApiServiceStub(
        private val updateExpenseResult: ApiResult = ApiResult.Throw(
            IllegalStateException("updateExpense not configured"),
        ),
        private val confirmExpenseResult: ApiResult = ApiResult.Throw(
            IllegalStateException("confirmExpense not configured"),
        ),
        private val rejectExpenseResult: ApiResult = ApiResult.Throw(
            IllegalStateException("rejectExpense not configured"),
        ),
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        override suspend fun updateExpense(
            id: Long,
            request: ExpenseUpdateRequest,
        ): ExpenseDto = when (val r = updateExpenseResult) {
            is ApiResult.Success -> r.dto
            is ApiResult.Throw -> throw r.exception
        }

        override suspend fun confirmExpense(
            id: Long,
            request: ExpenseStateTokenRequest,
        ): ExpenseDto = when (val r = confirmExpenseResult) {
            is ApiResult.Success -> r.dto
            is ApiResult.Throw -> throw r.exception
        }

        override suspend fun rejectExpense(
            id: Long,
            request: ExpenseStateTokenRequest,
        ): ExpenseDto = when (val r = rejectExpenseResult) {
            is ApiResult.Success -> r.dto
            is ApiResult.Throw -> throw r.exception
        }
    }

    private fun httpException(code: Int, body: String): HttpException {
        val raw = Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://api.example.com/").build())
            .code(code)
            .message("test")
            .body(body.toResponseBody("application/json".toMediaTypeOrNull()))
            .build()
        return HttpException(retrofit2.Response.error<ExpenseDto>(body.toResponseBody("application/json".toMediaTypeOrNull()), raw))
    }
}
