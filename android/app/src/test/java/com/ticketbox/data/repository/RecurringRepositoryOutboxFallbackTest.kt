package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.data.remote.dto.addRecurringWireAdapters
import com.ticketbox.domain.model.RecurringItem
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RecurringRepositoryOutboxFallbackTest {
    private fun baselineItem(): RecurringItem = successDto().toDomain().copy(
        merchant = "房租",
        merchantKey = "房租",
        baselineAmountCents = 350000,
        nextExpectedDate = "2026-09-01",
        lastAmountCents = 360000,
        occurrenceCount = 8,
        lastSeenAt = "2026-08-01T00:00:00Z",
        confidence = "high",
        source = "candidate",
        rowVersion = 7,
    )

    private fun successDto(): RecurringItemDto = RecurringItemDto(
        publicId = "recurring-1",
        ledgerId = "family",
        merchant = "房租",
        merchantKey = "房租",
        frequency = "monthly",
        baselineAmountCents = 350000,
        lastAmountCents = 350000,
        occurrenceCount = 0,
        lastSeenAt = null,
        nextExpectedDate = "2026-09-01",
        status = "active",
        confidence = null,
        source = "manual",
        createdAt = "2026-08-30T00:00:00Z",
        updatedAt = "2026-08-30T00:00:00Z",
        rowVersion = 1,
        pausedAt = null,
        archivedAt = null,
    )

    private fun moshi(): Moshi = Moshi.Builder()
        .addRecurringWireAdapters()
        .add(KotlinJsonAdapterFactory())
        .build()

    private class ServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private sealed interface ApiResult {
        data class Success(val dto: RecurringItemDto) : ApiResult
        data class Throw(val error: Throwable) : ApiResult
    }

    private class ApiStub(
        private val createResult: ApiResult,
        private val updateResult: ApiResult = createResult,
        delegate: ApiService = FakeApiService(mutableListOf(), 0),
    ) : ApiService by delegate {
        var createKey: String? = null
        var updateKey: String? = null

        override suspend fun createRecurringItem(
            request: RecurringItemCreateRequestDto,
            idempotencyKey: String,
        ): RecurringItemDto {
            createKey = idempotencyKey
            return createResult.resolve()
        }

        override suspend fun updateRecurringItem(
            publicId: String,
            request: RecurringItemUpdateRequestDto,
            idempotencyKey: String,
        ): RecurringItemDto {
            updateKey = idempotencyKey
            return updateResult.resolve()
        }

        private fun ApiResult.resolve(): RecurringItemDto = when (this) {
            is ApiResult.Success -> dto
            is ApiResult.Throw -> throw error
        }
    }

    private data class Harness(
        val repository: RecurringRepository,
        val binding: LogicalSessionBinding,
    )

    private fun harness(
        api: ApiService,
        role: String = "owner",
        outbox: OutboxRepository? = null,
    ): Harness {
        val session = TestSessionFixture().apply {
            saveToken("session-token")
            if (role != "owner") switchLedgerForFixture("owner", "我的小票夹", role)
        }
        val provider = testApiServiceProvider(ServiceFactory(api), session)
        val adapters = moshi()
        return Harness(
            repository = RecurringRepository(
                apiProvider = provider,
                outbox = outbox,
                createAdapter = adapters.adapter(RecurringItemCreateRequestDto::class.java),
                updateAdapter = adapters.adapter(RecurringItemUpdateRequestDto::class.java),
            ),
            binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding()),
        )
    }

    @Test
    fun `manual create success publishes server fact without queue row`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val api = ApiStub(ApiResult.Success(successDto()))
        val harness = harness(api, outbox = outbox)

        val outcome = harness.repository.createAllowingOffline(
            expectedBinding = harness.binding,
            draft = RecurringItemDraft("房租", 350000, "2026-09-01"),
        ).getOrThrow() as RecurringSaveOutcome.Synced

        assertEquals("recurring-1", outcome.item.publicId)
        assertEquals(0, dao.rows.size)
        assertFalse(api.createKey.isNullOrBlank())
    }

    @Test
    fun `manual create IOException queues same durable intent key without fabricating fact`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val api = ApiStub(ApiResult.Throw(IOException("offline")))
        val harness = harness(api, outbox = outbox)

        val outcome = harness.repository.createAllowingOffline(
            expectedBinding = harness.binding,
            draft = RecurringItemDraft("房租", 350000, null),
        ).getOrThrow() as RecurringSaveOutcome.Queued

        assertEquals(RecurringPendingKind.CREATE, outcome.intent.kind)
        assertEquals("房租", outcome.intent.merchant)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.CreateRecurringItem.wireValue, row.type)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals(0, row.expectedRowVersion)
        assertEquals(api.createKey, row.idempotencyKey)
        assertTrue(row.targetId.endsWith(requireNotNull(row.idempotencyKey)))
    }

    @Test
    fun `edit IOException queues OCC patch and preserves observed provenance in published baseline`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val api = ApiStub(
            createResult = ApiResult.Success(successDto()),
            updateResult = ApiResult.Throw(IOException("offline")),
        )
        val baseline = baselineItem()
        val harness = harness(api, outbox = outbox)

        val outcome = harness.repository.updateAllowingOffline(
            expectedBinding = harness.binding,
            baseline = baseline,
            patch = RecurringItemPatch(
                baselineAmountCents = 355000,
                nextExpectedDate = RecurringDateEdit.changed(null),
            ),
        ).getOrThrow() as RecurringSaveOutcome.Queued

        assertEquals(RecurringPendingKind.UPDATE, outcome.intent.kind)
        assertEquals(baseline.publicId, outcome.intent.publicId)
        assertEquals(null, outcome.intent.nextExpectedDate)
        assertTrue(outcome.intent.nextExpectedDateChanged)
        assertEquals(360000, baseline.lastAmountCents, "published observation must stay untouched")
        assertEquals(8, baseline.occurrenceCount)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.UpdateRecurringItem.wireValue, row.type)
        assertEquals("recurring_item:${baseline.publicId}", row.targetId)
        assertEquals(7, row.expectedRowVersion)
        assertEquals(api.updateKey, row.idempotencyKey)
        assertTrue("\"expected_row_version\":0" in row.payload)
        assertTrue("\"next_expected_date\":null" in row.payload)
    }

    @Test
    fun `viewer cannot create or enqueue a recurring item`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val api = ApiStub(ApiResult.Throw(IllegalStateException("network must not run")))
        val harness = harness(api, role = "viewer", outbox = outbox)

        val result = harness.repository.createAllowingOffline(
            expectedBinding = harness.binding,
            draft = RecurringItemDraft("房租", 350000, null),
        )

        assertTrue(result.isFailure)
        assertEquals("permission_denied", (result.exceptionOrNull() as RepositoryException).errorCode)
        assertEquals(0, dao.rows.size)
        assertEquals(null, api.createKey)
    }

    @Test
    fun `local recurring validation exposes stable codes without localized repository copy`() = runTest {
        val api = ApiStub(ApiResult.Success(successDto()))
        val harness = harness(api)
        val baseline = baselineItem()
        val failures = listOf(
            harness.repository.createAllowingOffline(
                harness.binding,
                RecurringItemDraft(" ", 1, null),
            ),
            harness.repository.createAllowingOffline(
                harness.binding,
                RecurringItemDraft("房租", 0, null),
            ),
            harness.repository.updateAllowingOffline(
                harness.binding,
                baseline.copy(publicId = ""),
                RecurringItemPatch(merchant = "新名称"),
            ),
            harness.repository.updateAllowingOffline(
                harness.binding,
                baseline.copy(rowVersion = 0),
                RecurringItemPatch(merchant = "新名称"),
            ),
            harness.repository.updateAllowingOffline(
                harness.binding,
                baseline,
                RecurringItemPatch(),
            ),
        )

        assertEquals(
            listOf(
                "recurring_merchant_required",
                "amount_invalid",
                "recurring_item_not_found",
                "state_conflict",
                "recurring_item_no_changes",
            ),
            failures.map { (it.exceptionOrNull() as RepositoryException).errorCode },
        )
        assertTrue(failures.all(Result<RecurringSaveOutcome>::isFailure))
        assertEquals(null, api.createKey)
        assertEquals(null, api.updateKey)
    }

    @Test
    fun `durable recurring rows are exposed as pending intents not published facts`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapters = moshi()
        outbox.enqueue(
            type = PendingMutationType.CreateRecurringItem,
            targetId = "recurring_item_create:create-key",
            payloadJson = adapters.adapter(RecurringItemCreateRequestDto::class.java).toJson(
                RecurringItemCreateRequestDto("房租", 350000, "2026-09-01"),
            ),
            expectedRowVersion = 0,
            idempotencyKey = "create-key",
        )
        val updateRowId = outbox.enqueue(
            type = PendingMutationType.UpdateRecurringItem,
            targetId = "recurring_item:recurring-1",
            payloadJson = adapters.adapter(RecurringItemUpdateRequestDto::class.java).toJson(
                RecurringItemUpdateRequestDto(expectedRowVersion = 0, baselineAmountCents = 355000),
            ),
            expectedRowVersion = 7,
            idempotencyKey = "update-key",
        )
        outbox.markConflict(updateRowId, "state_conflict")
        val harness = harness(ApiStub(ApiResult.Success(successDto())), outbox = outbox)

        val intents = harness.repository.observePendingIntents().first()

        assertEquals(listOf(RecurringPendingKind.CREATE, RecurringPendingKind.UPDATE), intents.map { it.kind })
        assertEquals(listOf(RecurringPendingState.WAITING, RecurringPendingState.CONFLICT), intents.map { it.state })
        assertEquals(listOf("房租", null), intents.map { it.merchant })
        assertEquals(listOf(350000L, 355000L), intents.map { it.baselineAmountCents })
    }
}
