package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.GoalUpdate
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice F contract tests for
 * [ReportsRepository.updateGoalAllowingOffline]. Mirrors
 * [RuleRepositoryOutboxFallbackTest]:
 *
 * - direct 2xx → GoalSaveOutcome.Synced(server goal). No row enqueued, key sent.
 * - IOException → GoalSaveOutcome.Queued(optimistic goal). Row enqueued, token
 *   stripped to 0L, same key as the direct attempt.
 */
class ReportsRepositoryOutboxFallbackTest {

    private fun baselineGoal(): Goal = Goal(
        publicId = "goal-1",
        ledgerId = "family",
        name = "本月餐饮",
        goalType = "spending_limit",
        period = "monthly",
        month = "2026-05",
        category = "餐饮",
        targetAmountCents = 80000,
        spentAmountCents = 64000,
        remainingAmountCents = 16000,
        progressPercent = 80,
        progressState = GoalProgressState.NearLimit,
        status = "active",
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-13T00:00:00Z",
        rowVersion = 3L,
        archivedAt = null,
    )

    private fun successDto(): GoalDto = GoalDto(
        publicId = "goal-1",
        ledgerId = "family",
        name = "本月餐饮",
        goalType = "spending_limit",
        period = "monthly",
        month = "2026-05",
        category = "购物",
        targetAmountCents = 90000,
        spentAmountCents = 64000,
        remainingAmountCents = 26000,
        progressPercent = 71,
        progressState = "on_track",
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
        data class Success(val dto: GoalDto) : ApiResult
        data class Throw(val exception: Throwable) : ApiResult
    }

    private class ApiServiceStub(
        private val updateGoalResult: ApiResult,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        // ADR-0042: capture the key the repo supplies so the test can assert it
        // matches the enqueued row's key. Captured before the result is applied
        // so the IOException path still sees it.
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun updateGoal(
            publicId: String,
            request: GoalUpdateRequestDto,
            idempotencyKey: String?,
            timezone: String?,
        ): GoalDto {
            lastIdempotencyKey = idempotencyKey
            return when (val r = updateGoalResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }
    }

    private fun buildRepository(
        api: ApiService,
        outbox: OutboxRepository? = null,
        adapter: com.squareup.moshi.JsonAdapter<GoalUpdateRequestDto>? = null,
    ): ReportsRepository = ReportsRepository(
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        outbox = outbox,
        goalUpdateAdapter = adapter,
    )

    @Test
    fun `direct 2xx returns Synced with server goal, no enqueue`() = runTest {
        val baseline = baselineGoal()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(GoalUpdateRequestDto::class.java)
        val api = ApiServiceStub(updateGoalResult = ApiResult.Success(successDto()))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateGoalAllowingOffline(
            baseline = baseline,
            update = GoalUpdate(expectedRowVersion = baseline.rowVersion, category = "购物", targetAmountCents = 90000),
        ).getOrThrow() as GoalSaveOutcome.Synced

        assertEquals("购物", outcome.goal.category)
        assertEquals(4L, outcome.goal.rowVersion)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
        assertTrue(api.lastIdempotencyKey != null, "direct PATCH must carry a key")
    }

    @Test
    fun `IOException returns Queued with optimistic goal + enqueues row`() = runTest {
        val baseline = baselineGoal()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(GoalUpdateRequestDto::class.java)
        val api = ApiServiceStub(updateGoalResult = ApiResult.Throw(IOException("net out")))

        val repo = buildRepository(api, outbox, adapter)
        val outcome = repo.updateGoalAllowingOffline(
            baseline = baseline,
            update = GoalUpdate(expectedRowVersion = baseline.rowVersion, category = "购物", targetAmountCents = 90000),
        ).getOrThrow() as GoalSaveOutcome.Queued

        // Optimistic projection: submitted fields over baseline; rowVersion
        // unchanged (NOT a server token).
        assertEquals("购物", outcome.goal.category)
        assertEquals(90000, outcome.goal.targetAmountCents)
        assertEquals(baseline.name, outcome.goal.name)
        assertEquals(baseline.rowVersion, outcome.goal.rowVersion)

        // Row enqueued with correct target / token.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.UpdateGoal.wireValue, row.type)
        assertEquals("goal:${baseline.publicId}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // codex round-8 P3#5: payload MUST NOT carry the live token — it's
        // neutralised to 0L; the dispatcher overwrites from row.expectedRowVersion.
        assertTrue(
            "\"expected_row_version\":0" in row.payload,
            "payload token must be neutralised to 0: ${row.payload}",
        )
        // ADR-0042: the direct attempt + the enqueued row share ONE intent-time
        // key so a committed-but-unseen PATCH replays with it.
        assertEquals(
            api.lastIdempotencyKey,
            row.idempotencyKey,
            "enqueued row must carry the same key the direct PATCH used",
        )
        assertTrue(row.idempotencyKey != null, "UpdateGoal row must carry an idempotency key")
    }

    @Test
    fun `IOException without outbox wired stays as failure`() = runTest {
        val api = ApiServiceStub(updateGoalResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox = null, adapter = null)

        val result = repo.updateGoalAllowingOffline(
            baseline = baselineGoal(),
            update = GoalUpdate(expectedRowVersion = baselineGoal().rowVersion, category = "购物"),
        )

        assertTrue(result.isFailure)
    }
}
