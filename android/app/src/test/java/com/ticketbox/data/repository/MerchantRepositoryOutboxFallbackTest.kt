package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.domain.model.MerchantAlias
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
import kotlin.test.assertTrue

/**
 * ADR-0038 PR-2g.5 contract tests for
 * [MerchantRepository.deleteMerchantAliasAllowingOffline]. Mirrors
 * the DELETE half of [RuleRepositoryOutboxFallbackTest] — same
 * boundaries, ``merchant_alias:<publicId>`` target.
 */
class MerchantRepositoryOutboxFallbackTest {

    private fun baselineAlias(updatedAt: String = "2026-05-20T12:00:00.000Z"): MerchantAlias =
        MerchantAlias(
            publicId = "alias-public-1",
            canonicalMerchant = "标准商家",
            canonicalKey = "标准商家",
            alias = "别名 A",
            aliasKey = "别名 A",
            enabled = true,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = updatedAt,
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
        deleteAdapter: com.squareup.moshi.JsonAdapter<MerchantAliasDeleteRequest>? = null,
        updateAdapter: com.squareup.moshi.JsonAdapter<MerchantAliasUpdateRequest>? = null,
    ): MerchantRepository = MerchantRepository(
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        outbox = outbox,
        merchantAliasDeleteAdapter = deleteAdapter,
        merchantAliasUpdateAdapter = updateAdapter,
    )

    private fun aliasDto(updatedAt: String = "2026-05-20T13:00:00.000Z"): MerchantAliasDto =
        MerchantAliasDto(
            publicId = "alias-public-1",
            canonicalMerchant = "标准商家",
            canonicalKey = "标准商家",
            alias = "新别名",
            aliasKey = "新别名",
            enabled = true,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = updatedAt,
        )

    @Test
    fun `direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineAlias()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(MerchantAliasDeleteRequest::class.java)
        // FakeApiService.deleteMerchantAlias returns StatusDto("ok") —
        // success path.
        val api = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)

        val repo = buildRepository(api, outbox = outbox, deleteAdapter = adapter)
        val outcome = repo.deleteMerchantAliasAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is DeleteOutcome.Synced)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }

    @Test
    fun `IOException returns Queued + enqueues row without token in payload`() = runTest {
        val baseline = baselineAlias()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(MerchantAliasDeleteRequest::class.java)
        val api = ThrowingDeleteAliasApiService(IOException("net out"))

        val repo = buildRepository(api, outbox = outbox, deleteAdapter = adapter)
        val outcome = repo.deleteMerchantAliasAllowingOffline(baseline).getOrThrow()

        assertTrue(outcome is DeleteOutcome.Queued)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.DeleteMerchantAlias.wireValue, row.type)
        assertEquals("merchant_alias:${baseline.publicId}", row.targetId)
        assertEquals(baseline.updatedAt, row.expectedUpdatedAt)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // codex round-8 P3#5: token must not be in payload.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed token: ${row.payload}",
        )
    }

    @Test
    fun `HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(MerchantAliasDeleteRequest::class.java)
        val api = ThrowingDeleteAliasApiService(
            httpException(409, """{"error":"state_conflict","message":"别名已修改"}"""),
        )

        val repo = buildRepository(api, outbox = outbox, deleteAdapter = adapter)
        val result = repo.deleteMerchantAliasAllowingOffline(baselineAlias())

        assertTrue(result.isFailure, "409 conflict must surface, not queue")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `HttpException 500 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(MerchantAliasDeleteRequest::class.java)
        val api = ThrowingDeleteAliasApiService(httpException(500, """{"error":"internal"}"""))

        val repo = buildRepository(api, outbox = outbox, deleteAdapter = adapter)
        val result = repo.deleteMerchantAliasAllowingOffline(baselineAlias())

        assertTrue(result.isFailure, "5xx must surface, not queue")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `IOException without outbox wired stays as failure`() = runTest {
        val api = ThrowingDeleteAliasApiService(IOException("net out"))
        val repo = buildRepository(api, outbox = null, deleteAdapter = null)

        val result = repo.deleteMerchantAliasAllowingOffline(baselineAlias())

        assertTrue(result.isFailure)
    }

    // region — updateMerchantAliasAllowingOffline (PR-2g.6)

    @Test
    fun `update direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineAlias()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val updateAdapter = moshi().adapter(MerchantAliasUpdateRequest::class.java)
        val api = UpdateAliasApiServiceStub(UpdateAliasResult.Success(aliasDto()))

        val repo = buildRepository(api, outbox = outbox, updateAdapter = updateAdapter)
        val outcome = repo.updateMerchantAliasAllowingOffline(baseline, alias = "新别名")
            .getOrThrow()

        assertTrue(outcome is MerchantAliasSaveOutcome.Synced)
        assertEquals("新别名", outcome.alias.alias)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `update IOException returns Queued + enqueues row without token in payload`() = runTest {
        val baseline = baselineAlias()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val updateAdapter = moshi().adapter(MerchantAliasUpdateRequest::class.java)
        val api = UpdateAliasApiServiceStub(UpdateAliasResult.Throw(IOException("net out")))

        val repo = buildRepository(api, outbox = outbox, updateAdapter = updateAdapter)
        val outcome = repo.updateMerchantAliasAllowingOffline(
            baseline = baseline,
            enabled = false,
        ).getOrThrow()

        assertTrue(outcome is MerchantAliasSaveOutcome.Queued)
        assertEquals(false, outcome.alias.enabled, "optimistic projection flips enabled")
        assertEquals(baseline.alias, outcome.alias.alias, "non-submitted fields unchanged")
        assertEquals(baseline.updatedAt, outcome.alias.updatedAt, "pre-mutation token")

        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.UpdateMerchantAlias.wireValue, row.type)
        assertEquals("merchant_alias:${baseline.publicId}", row.targetId)
        assertEquals(baseline.updatedAt, row.expectedUpdatedAt)
        // round-8 P3#5: token NOT in payload.
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed token: ${row.payload}",
        )
    }

    @Test
    fun `update HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val updateAdapter = moshi().adapter(MerchantAliasUpdateRequest::class.java)
        val api = UpdateAliasApiServiceStub(
            UpdateAliasResult.Throw(
                httpExceptionForDto(409, """{"error":"state_conflict","message":"别名已修改"}"""),
            ),
        )

        val repo = buildRepository(api, outbox = outbox, updateAdapter = updateAdapter)
        val result = repo.updateMerchantAliasAllowingOffline(baselineAlias(), enabled = false)

        assertTrue(result.isFailure)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `update IOException without outbox wired stays as failure`() = runTest {
        val api = UpdateAliasApiServiceStub(UpdateAliasResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox = null, deleteAdapter = null, updateAdapter = null)

        val result = repo.updateMerchantAliasAllowingOffline(baselineAlias(), enabled = false)

        assertTrue(result.isFailure)
    }

    // endregion

    private sealed interface UpdateAliasResult {
        data class Success(val dto: MerchantAliasDto) : UpdateAliasResult
        data class Throw(val exception: Throwable) : UpdateAliasResult
    }

    /**
     * Stand-in ApiService that returns / throws the configured
     * result for updateMerchantAlias; everything else delegates.
     */
    private class UpdateAliasApiServiceStub(
        private val updateResult: UpdateAliasResult,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        override suspend fun updateMerchantAlias(
            publicId: String,
            request: MerchantAliasUpdateRequest,
        ): MerchantAliasDto = when (val r = updateResult) {
            is UpdateAliasResult.Success -> r.dto
            is UpdateAliasResult.Throw -> throw r.exception
        }
    }

    private fun httpExceptionForDto(code: Int, body: String): HttpException {
        val raw = Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://api.example.com/").build())
            .code(code)
            .message("test")
            .body(body.toResponseBody("application/json".toMediaTypeOrNull()))
            .build()
        return HttpException(
            retrofit2.Response.error<MerchantAliasDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }

    /**
     * Stand-in ApiService that throws a configured exception on
     * deleteMerchantAlias. Everything else delegates to FakeApiService
     * via interface delegation.
     */
    private class ThrowingDeleteAliasApiService(
        private val exception: Throwable,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        override suspend fun deleteMerchantAlias(
            publicId: String,
            request: MerchantAliasDeleteRequest,
        ): StatusDto = throw exception
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
            retrofit2.Response.error<StatusDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
