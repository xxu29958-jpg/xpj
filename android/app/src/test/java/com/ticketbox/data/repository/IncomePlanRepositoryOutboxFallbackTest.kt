package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice F contract tests for
 * [IncomePlanRepository.updateAllowingOffline]. Mirrors
 * [RuleRepositoryOutboxFallbackTest]:
 *
 * - direct 2xx → IncomePlanSaveOutcome.Synced(server plan). No row enqueued.
 * - IOException → IncomePlanSaveOutcome.Queued(optimistic plan). Row enqueued,
 *   token stripped to 0L, same key as the direct attempt.
 */
class IncomePlanRepositoryOutboxFallbackTest {

    private fun baselinePlan(): IncomePlan = IncomePlan(
        publicId = "plan-1",
        label = "工资",
        sourceType = IncomeSourceType.SALARY,
        amountCents = 1500000,
        payDay = 15,
        status = IncomePlanStatus.ACTIVE,
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-13T00:00:00Z",
        rowVersion = 3L,
        archivedAt = null,
    )

    private fun successDto(): IncomePlanDto = IncomePlanDto(
        publicId = "plan-1",
        label = "调薪后工资",
        sourceType = "salary",
        amountCents = 1800000,
        payDay = 15,
        status = "active",
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-20T13:00:00.000Z",
        rowVersion = 4L,
        archivedAt = null,
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

    private sealed interface ApiResult {
        data class Success(val dto: IncomePlanDto) : ApiResult
        data class Throw(val exception: Throwable) : ApiResult
    }

    private class ApiServiceStub(
        private val updatePlanResult: ApiResult,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun updateIncomePlan(
            publicId: String,
            request: IncomePlanUpdateRequestDto,
            idempotencyKey: String?,
        ): IncomePlanDto {
            lastIdempotencyKey = idempotencyKey
            return when (val r = updatePlanResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }
    }

    private fun buildRepository(
        api: ApiService,
        outbox: OutboxRepository? = null,
        adapter: com.squareup.moshi.JsonAdapter<IncomePlanUpdateRequestDto>? = null,
    ): IncomePlanRepository = IncomePlanRepository(
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        outbox = outbox,
        incomePlanUpdateAdapter = adapter,
    )

    @Test
    fun `direct 2xx returns Synced with server plan, no enqueue`() = runTest {
        val baseline = baselinePlan()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(IncomePlanUpdateRequestDto::class.java)
        val api = ApiServiceStub(updatePlanResult = ApiResult.Success(successDto()))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateAllowingOffline(
            baseline = baseline,
            patch = IncomePlanPatch(expectedRowVersion = baseline.rowVersion, amountCents = 1800000, label = "调薪后工资"),
        ).getOrThrow() as IncomePlanSaveOutcome.Synced

        assertEquals("调薪后工资", outcome.plan.label)
        assertEquals(1800000, outcome.plan.amountCents)
        assertEquals(4L, outcome.plan.rowVersion)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
        assertTrue(api.lastIdempotencyKey != null, "direct PATCH must carry a key")
    }

    @Test
    fun `IOException returns Queued with optimistic plan + enqueues row`() = runTest {
        val baseline = baselinePlan()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(IncomePlanUpdateRequestDto::class.java)
        val api = ApiServiceStub(updatePlanResult = ApiResult.Throw(IOException("net out")))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateAllowingOffline(
            baseline = baseline,
            patch = IncomePlanPatch(expectedRowVersion = baseline.rowVersion, amountCents = 1800000, label = "调薪后工资"),
        ).getOrThrow() as IncomePlanSaveOutcome.Queued

        // Optimistic projection: submitted fields over baseline; rowVersion
        // unchanged (NOT a server token).
        assertEquals("调薪后工资", outcome.plan.label)
        assertEquals(1800000, outcome.plan.amountCents)
        assertEquals(baseline.payDay, outcome.plan.payDay)
        assertEquals(baseline.rowVersion, outcome.plan.rowVersion)

        // Row enqueued with correct target / token.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.UpdateIncomePlan.wireValue, row.type)
        assertEquals("income_plan:${baseline.publicId}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // Payload carries the submitted edits.
        assertTrue("调薪后工资" in row.payload, "payload must carry the label: ${row.payload}")
        // codex round-8 P3#5: token neutralised to 0L; dispatcher overwrites
        // from row.expectedRowVersion on replay.
        assertTrue(
            "\"expected_row_version\":0" in row.payload,
            "payload token must be neutralised to 0: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertEquals(
            api.lastIdempotencyKey,
            row.idempotencyKey,
            "enqueued row must carry the same key the direct PATCH used",
        )
        assertTrue(row.idempotencyKey != null, "UpdateIncomePlan row must carry an idempotency key")
    }

    @Test
    fun `IOException without outbox wired stays as failure`() = runTest {
        val api = ApiServiceStub(updatePlanResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox = null, adapter = null)

        val result = repo.updateAllowingOffline(
            baseline = baselinePlan(),
            patch = IncomePlanPatch(expectedRowVersion = baselinePlan().rowVersion, amountCents = 1800000),
        )

        assertTrue(result.isFailure)
    }
}
