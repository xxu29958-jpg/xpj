package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.domain.model.CategoryRule
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
 * ADR-0038 PR-2g.4 contract tests for
 * [RuleRepository.updateCategoryRuleAllowingOffline]. Mirrors
 * [ExpensePendingRepositoryOutboxFallbackTest] (PR-2g.3) — same
 * boundaries, different mutation type.
 *
 * Two semantic boundaries enforced:
 *
 * 1. Offline-aware ``updateCategoryRuleAllowingOffline``:
 *    - direct 2xx → CategoryRuleSaveOutcome.Synced(server rule). No row enqueued.
 *    - IOException → CategoryRuleSaveOutcome.Queued(optimistic rule). Row enqueued.
 *    - HttpException (409 / 422 / 500) → Result.failure. No row enqueued.
 *
 * 2. Direct ``updateCategoryRule`` is unchanged from PR-1 and not
 *    re-tested here (its contract isn't affected by this PR).
 */
class RuleRepositoryOutboxFallbackTest {

    private fun baselineRule(updatedAt: String = "2026-05-20T12:00:00.000Z"): CategoryRule =
        CategoryRule(
            id = 7L,
            keyword = "原关键词",
            category = "餐饮",
            enabled = true,
            priority = 50,
            amountMinCents = null,
            amountMaxCents = null,
            sourceContains = null,
            tagContains = null,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = updatedAt,
            rowVersion = 1L,
        )

    private fun successDto(serverUpdatedAt: String = "2026-05-20T13:00:00.000Z"): CategoryRuleDto =
        CategoryRuleDto(
            id = 7L,
            keyword = "新关键词",
            category = "餐饮",
            enabled = true,
            priority = 50,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = serverUpdatedAt,
            rowVersion = 2L,
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
        adapter: com.squareup.moshi.JsonAdapter<CategoryRuleUpdateRequest>? = null,
        deleteAdapter: com.squareup.moshi.JsonAdapter<com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest>? = null,
    ): RuleRepository = RuleRepository(
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        outbox = outbox,
        categoryRuleUpdateAdapter = adapter,
        categoryRuleDeleteAdapter = deleteAdapter,
    )

    // region — saveExpenseAllowingOffline mirror

    @Test
    fun `direct 2xx returns Synced with server rule, no enqueue`() = runTest {
        val baseline = baselineRule()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(CategoryRuleUpdateRequest::class.java)
        val api = ApiServiceStub(updateCategoryRuleResult = ApiResult.Success(successDto()))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateCategoryRuleAllowingOffline(
            baseline = baseline,
            keyword = "新关键词",
        ).getOrThrow() as CategoryRuleSaveOutcome.Synced

        // Server-confirmed: token is the post-PATCH server one.
        assertNotEquals(baseline.updatedAt, outcome.rule.updatedAt)
        assertEquals("新关键词", outcome.rule.keyword)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }

    @Test
    fun `IOException returns Queued with optimistic rule + enqueues row`() = runTest {
        val baseline = baselineRule()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(CategoryRuleUpdateRequest::class.java)
        val api = ApiServiceStub(updateCategoryRuleResult = ApiResult.Throw(IOException("net out")))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateCategoryRuleAllowingOffline(
            baseline = baseline,
            keyword = "新关键词",
            priority = 99,
        ).getOrThrow() as CategoryRuleSaveOutcome.Queued

        // Optimistic projection: user's submitted fields applied
        // over baseline; updatedAt unchanged (NOT a server token).
        assertEquals("新关键词", outcome.rule.keyword)
        assertEquals(99, outcome.rule.priority)
        assertEquals(baseline.category, outcome.rule.category)
        assertEquals(baseline.enabled, outcome.rule.enabled)
        assertEquals(baseline.updatedAt, outcome.rule.updatedAt)

        // Row enqueued with correct target / token.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.UpdateCategoryRule.wireValue, row.type)
        assertEquals("category_rule:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // Payload contains the submitted edits.
        assertTrue("新关键词" in row.payload, "payload must carry keyword: ${row.payload}")
        // codex round-8 P3#5: payload MUST NOT carry the token —
        // outbox row's expectedRowVersion is single source of truth.
        // CategoryRuleUpdateRequest.expectedRowVersion is non-nullable
        // Long, so we set it to 0L before serialising; dispatcher
        // overwrites it from row.expectedRowVersion on replay.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed baseline token: ${row.payload}",
        )
        assertTrue(
            "\"expected_row_version\":0" in row.payload,
            "payload token must be neutralised to 0: ${row.payload}",
        )
        // ADR-0042: the direct attempt + the enqueued row share ONE intent-time
        // key so a committed-but-unseen PATCH replays with it (server HITs the
        // recorded success, not a false 409 on the stale token).
        assertEquals(
            api.lastUpdateIdempotencyKey,
            row.idempotencyKey,
            "enqueued row must carry the same key the direct PATCH used",
        )
        assertTrue(row.idempotencyKey != null, "UpdateCategoryRule row must carry an idempotency key")
    }

    @Test
    fun `IOException with enabled toggle returns Queued with flipped enabled`() = runTest {
        // The toggleCategoryRule ViewModel path uses just the
        // ``enabled`` field. Optimistic projection should reflect
        // the flip.
        val baseline = baselineRule().copy(enabled = true)
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(CategoryRuleUpdateRequest::class.java)
        val api = ApiServiceStub(updateCategoryRuleResult = ApiResult.Throw(IOException("net out")))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateCategoryRuleAllowingOffline(
            baseline = baseline,
            enabled = false,
        ).getOrThrow() as CategoryRuleSaveOutcome.Queued

        assertEquals(false, outcome.rule.enabled)
        assertEquals(baseline.keyword, outcome.rule.keyword)  // unchanged
        assertEquals(1, dao.rows.size)
    }

    @Test
    fun `HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(CategoryRuleUpdateRequest::class.java)
        val api = ApiServiceStub(
            updateCategoryRuleResult = ApiResult.Throw(
                httpException(409, """{"error":"state_conflict","message":"规则已修改"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.updateCategoryRuleAllowingOffline(baselineRule(), keyword = "x")

        assertTrue(result.isFailure, "409 conflict must surface, not silently queue")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `HttpException 422 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(CategoryRuleUpdateRequest::class.java)
        val api = ApiServiceStub(
            updateCategoryRuleResult = ApiResult.Throw(
                httpException(422, """{"error":"invalid_priority"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.updateCategoryRuleAllowingOffline(baselineRule(), priority = -1)

        assertTrue(result.isFailure)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `HttpException 500 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(CategoryRuleUpdateRequest::class.java)
        val api = ApiServiceStub(
            updateCategoryRuleResult = ApiResult.Throw(
                httpException(500, """{"error":"internal"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.updateCategoryRuleAllowingOffline(baselineRule(), keyword = "x")

        assertTrue(result.isFailure, "5xx must surface, not queue (server reachable but unhappy)")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `IOException without outbox wired stays as failure`() = runTest {
        val api = ApiServiceStub(updateCategoryRuleResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox = null, adapter = null)

        val result = repo.updateCategoryRuleAllowingOffline(baselineRule(), keyword = "x")

        assertTrue(result.isFailure)
    }

    // endregion

    // region — deleteCategoryRuleAllowingOffline (PR-2g.5)

    @Test
    fun `delete direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineRule()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val deleteAdapter = moshi().adapter(com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest::class.java)
        // default deleteCategoryRuleException = null → success
        val api = ApiServiceStub()

        val repo = buildRepository(api, outbox = outbox, deleteAdapter = deleteAdapter)
        val outcome = repo.deleteCategoryRuleAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is DeleteOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `delete IOException returns Queued + enqueues row without token in payload`() = runTest {
        val baseline = baselineRule()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val deleteAdapter = moshi().adapter(com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest::class.java)
        val api = ApiServiceStub(deleteCategoryRuleException = IOException("net out"))

        val repo = buildRepository(api, outbox = outbox, deleteAdapter = deleteAdapter)
        val outcome = repo.deleteCategoryRuleAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is DeleteOutcome.Queued)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.DeleteCategoryRule.wireValue, row.type)
        assertEquals("category_rule:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        // codex round-8 P3#5: token must not be in payload.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed token: ${row.payload}",
        )
        assertTrue(
            "\"expected_row_version\":0" in row.payload,
            "payload token must be neutralised to 0: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertEquals(
            api.lastDeleteIdempotencyKey,
            row.idempotencyKey,
            "enqueued row must carry the same key the direct DELETE used",
        )
        assertTrue(row.idempotencyKey != null, "DeleteCategoryRule row must carry an idempotency key")
    }

    @Test
    fun `delete HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val deleteAdapter = moshi().adapter(com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest::class.java)
        val api = ApiServiceStub(
            deleteCategoryRuleException = httpException(
                409,
                """{"error":"state_conflict","message":"规则已修改"}""",
            ),
        )
        val repo = buildRepository(api, outbox = outbox, deleteAdapter = deleteAdapter)

        val result = repo.deleteCategoryRuleAllowingOffline(baselineRule())

        assertTrue(result.isFailure)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `delete IOException without outbox wired stays as failure`() = runTest {
        val api = ApiServiceStub(deleteCategoryRuleException = IOException("net out"))
        val repo = buildRepository(api, outbox = null, adapter = null, deleteAdapter = null)

        val result = repo.deleteCategoryRuleAllowingOffline(baselineRule())

        assertTrue(result.isFailure)
    }

    @Test
    fun `delete IOException after ledger switch mid-flight does NOT enqueue`() = runTest {
        // [codex round-13 P1] Same session-race as the expense
        // saveExpenseAllowingOffline path. Without the post-
        // IOException ``requireStillActive`` check, a DELETE
        // started under ledger A would queue into ledger B's
        // outbox after a mid-flight switch.
        val baseline = baselineRule()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val deleteAdapter = moshi().adapter(com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest::class.java)

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

        val api = object : ApiService by FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ) {
            override suspend fun deleteCategoryRule(
                id: Long,
                request: com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest,
                idempotencyKey: String?,
            ): com.ticketbox.data.remote.dto.StatusDto {
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

        val repo = RuleRepository(
            apiClient = TestApiServiceFactory(api),
            settingsStore = settings,
            tokenStore = tokens,
            outbox = outbox,
            categoryRuleDeleteAdapter = deleteAdapter,
        )

        val result = repo.deleteCategoryRuleAllowingOffline(baseline)

        assertTrue(
            result.isFailure,
            "mid-flight ledger switch must surface, not silently queue under new session",
        )
        assertEquals(
            0,
            dao.rows.size,
            "no row should be enqueued when session changed between bind and IOException",
        )
    }

    // endregion

    private sealed interface ApiResult {
        data class Success(val dto: CategoryRuleDto) : ApiResult
        data class Throw(val exception: Throwable) : ApiResult
    }

    private class ApiServiceStub(
        // Update path: configured per test with Success(dto) or
        // Throw(exception). Default success-with-stub-dto so a test
        // that only exercises the delete path doesn't have to set
        // both.
        private val updateCategoryRuleResult: ApiResult = ApiResult.Throw(
            IllegalStateException("updateCategoryRule not configured"),
        ),
        // Delete path: ``null`` exception means the call succeeds
        // (DELETE returns no body); a non-null exception is thrown.
        private val deleteCategoryRuleException: Throwable? = null,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        // ADR-0042: capture the Idempotency-Key the repository supplies on each
        // direct attempt so tests can assert it matches the enqueued row's key.
        // Captured before the result is applied so the IOException path still
        // sees it.
        var lastUpdateIdempotencyKey: String? = null
            private set
        var lastDeleteIdempotencyKey: String? = null
            private set

        override suspend fun updateCategoryRule(
            id: Long,
            request: CategoryRuleUpdateRequest,
            idempotencyKey: String?,
        ): CategoryRuleDto {
            lastUpdateIdempotencyKey = idempotencyKey
            return when (val r = updateCategoryRuleResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }

        override suspend fun deleteCategoryRule(
            id: Long,
            request: com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest,
            idempotencyKey: String?,
        ): com.ticketbox.data.remote.dto.StatusDto {
            lastDeleteIdempotencyKey = idempotencyKey
            deleteCategoryRuleException?.let { throw it }
            // Real ApiService returns StatusDto; production code
            // ignores the value (deleteCategoryRuleAllowingOffline
            // just maps success to DeleteOutcome.Synced).
            return com.ticketbox.data.remote.dto.StatusDto(status = "ok")
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
        return HttpException(
            retrofit2.Response.error<CategoryRuleDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
