package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtSourceTypes
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtAdjustmentRepositoryTest {
    @Test
    fun savePersistsSignedAmountTrimmedReasonAndOriginalVersionBeforeSchedulingWithoutDirectSend() = runTest {
        val fixture = DebtAdjustmentFixture()
        val id = fixture.save(amountCents = -5_000L, reason = "  减免部分  ").getOrThrow()

        assertTrue(fixture.api.calls.isEmpty())
        assertEquals(listOf(1), fixture.queueDepthAtSchedule)
        val stored = fixture.dao.rows.getValue(id)
        val payload = requireNotNull(fixture.adapters.debtAdjustmentAdapter.fromJson(stored.payload))
        assertEquals(PendingMutationType.RecordDebtAdjustment.wireValue, stored.type)
        assertEquals("debt:d1", stored.targetId)
        assertEquals(fixture.binding.ownerKey, stored.ownerKey)
        assertEquals(fixture.binding.ledgerId, stored.ledgerId)
        assertEquals(fixture.binding.sessionGeneration, payload.originSessionGeneration)
        assertEquals(fixture.binding.bindingRevision, payload.originBindingRevision)
        assertEquals(1, payload.revision)
        assertEquals(DebtAdjustmentSubject("d1", "房东", "CNY"), payload.subject)
        assertEquals(DebtAdjustmentCreateRequestDto(-5_000L, "减免部分", 2L), payload.request)
        assertEquals(2L, stored.expectedRowVersion)
        assertTrue(!stored.idempotencyKey.isNullOrBlank())
        assertEquals(PendingMutationStatus.Pending.wireValue, stored.status)

        assertEquals(1, fixture.engine().drainOnce().done)
        val sent = fixture.api.calls.single()
        assertEquals("d1", sent.publicId)
        assertEquals(payload.request, sent.request)
        assertEquals(stored.idempotencyKey, sent.idempotencyKey)
    }

    @Test
    fun responseLostAfterAdjustmentCommitRecoversTheOriginalCommandAfterRepositoryRestart() = runTest {
        val fixture = DebtAdjustmentFixture()
        fixture.api.loseResponse = true
        val id = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(id)

        assertEquals(1, fixture.engine().drainOnce().retryable)
        assertEquals(PendingMutationStatus.Pending.wireValue, fixture.dao.rows.getValue(id).status)
        assertOriginalIntent(original, fixture.dao.rows.getValue(id))
        assertEquals(1, fixture.api.facts.size)

        val restartedClock = Clock.offset(fixture.clock, Duration.ofMinutes(2))
        val restartedOutbox = fixture.newOutbox(restartedClock)
        val restartedRepository = fixture.newRepository(restartedOutbox)
        val recovered = restartedRepository.observeAdjustments(fixture.binding, "d1").first().single()
        assertEquals(original.payload, recovered.row.payloadJson)
        assertEquals(DebtAdjustmentCreateRequestDto(3_000L, "补记借款", 2L), recovered.intent?.request)
        fixture.api.loseResponse = false

        assertEquals(1, fixture.engine(restartedOutbox, restartedClock).drainOnce().done)
        assertEquals(2, fixture.api.calls.size)
        assertEquals(fixture.api.calls[0], fixture.api.calls[1])
        assertEquals(original.idempotencyKey, fixture.api.calls[1].idempotencyKey)
        assertEquals(1, fixture.api.facts.size)
        assertEquals(3L, fixture.api.facts.values.single().second.rowVersion)
        assertEquals(53_000L, fixture.api.facts.values.single().second.remainingAmountCents)
        assertOriginalIntent(original, fixture.dao.rows.getValue(id))
        assertEquals(PendingMutationStatus.Done, restartedRepository.observeAdjustments(fixture.binding, "d1").first().single().row.status)
    }

    @Test
    fun successfulDrainDoesNotCascadeARefreshedVersionIntoAnotherStoredCommand() = runTest {
        val fixture = DebtAdjustmentFixture()
        val id = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        val payload = requireNotNull(fixture.adapters.debtAdjustmentAdapter.fromJson(original.payload))
        // Seed a separate stored command to detect an unauthorized cascade by the real drain engine.
        val followingId = fixture.outbox.enqueue(
            type = PendingMutationType.RecordDebtAdjustment,
            targetId = original.targetId,
            payloadJson = fixture.adapters.debtAdjustmentAdapter.toJson(payload.copy(
                request = DebtAdjustmentCreateRequestDto(7_000L, "另一笔调整", 7L),
            )),
            expectedRowVersion = 7L,
            idempotencyKey = "synthetic-following-adjustment",
        )
        val following = fixture.dao.rows.getValue(followingId)

        assertEquals(1, fixture.engine().drainOnce().done)

        assertEquals(1, fixture.api.calls.size)
        assertEquals(PendingMutationStatus.Done.wireValue, fixture.dao.rows.getValue(id).status)
        assertEquals(following, fixture.dao.rows.getValue(followingId))
    }

    @Test
    fun protocolUnknownConflictAndMissingTargetRefusalsKeepFailedOriginalBytes() = runTest {
        for (refusal in listOf(409 to "runtime_version_mismatch", 409 to "future_domain_refusal", 404 to "not_found")) {
            val fixture = DebtAdjustmentFixture()
            fixture.api.refusal = refusal
            val id = fixture.save().getOrThrow()
            val original = fixture.dao.rows.getValue(id)

            val result = fixture.engine().drainOnce()

            assertEquals(1, result.failures, refusal.toString())
            assertEquals(0, result.discarded, refusal.toString())
            val pending = fixture.pending()
            assertEquals(PendingMutationStatus.Failed, pending.row.status)
            assertTrue(pending.hasSupportedIntent)
            assertNull(pending.row.completedAt)
            assertOriginalIntent(original, fixture.dao.rows.getValue(id))
            if (refusal.second == "runtime_version_mismatch") {
                assertEquals("runtime_version_mismatch", pending.row.lastError)
            }
            assertEquals(1, fixture.api.calls.size)
            assertTrue(fixture.api.facts.isEmpty())
            assertEquals(0, fixture.engine().drainOnce().attempted)
            assertEquals(1, fixture.api.calls.size)
        }
    }

    @Test
    fun supportedFailedIntentRetriesWithItsOriginalKeyBodyAndOcc() = runTest {
        val fixture = DebtAdjustmentFixture()
        fixture.api.refusal = 409 to "future_domain_refusal"
        val id = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        fixture.engine().drainOnce()

        fixture.repository.recover(fixture.binding, fixture.pending(), drop = false).getOrThrow()

        assertEquals(PendingMutationStatus.Pending.wireValue, fixture.dao.rows.getValue(id).status)
        assertOriginalIntent(original, fixture.dao.rows.getValue(id))
        fixture.api.refusal = null
        assertEquals(1, fixture.engine().drainOnce().done)
        assertEquals(2, fixture.api.calls.size)
        assertEquals(fixture.api.calls.first(), fixture.api.calls.last())
        assertEquals(1, fixture.api.facts.size)
        assertOriginalIntent(original, fixture.dao.rows.getValue(id))
    }

    @Test
    fun stateConflictRemainsConflictWithoutFreshOccOrAnotherSubmission() = runTest {
        val fixture = DebtAdjustmentFixture()
        fixture.api.refusal = 409 to "state_conflict"
        val id = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(id)

        assertEquals(1, fixture.engine().drainOnce().conflicts)
        val conflict = fixture.pending()
        assertEquals(PendingMutationStatus.Conflict, conflict.row.status)
        fixture.repository.recover(fixture.binding, conflict, drop = false)

        assertEquals(PendingMutationStatus.Conflict.wireValue, fixture.dao.rows.getValue(id).status)
        assertOriginalIntent(original, fixture.dao.rows.getValue(id))
        assertEquals(0, fixture.engine().drainOnce().attempted)
        assertEquals(1, fixture.api.calls.size)
        assertTrue(fixture.api.facts.isEmpty())
    }

    @Test
    fun unsupportedPayloadCannotRetryOrSendAndRemainsUntilExplicitDrop() = runTest {
        val fixture = DebtAdjustmentFixture()
        val id = fixture.save().getOrThrow()
        val row = fixture.dao.rows.getValue(id)
        val payload = requireNotNull(fixture.adapters.debtAdjustmentAdapter.fromJson(row.payload))
        val unsupported = row.copy(payload = fixture.adapters.debtAdjustmentAdapter.toJson(payload.copy(revision = 99)))
        fixture.dao.rows[id] = unsupported

        assertEquals(1, fixture.engine().drainOnce().failures)
        val pending = fixture.pending()
        assertFalse(pending.hasSupportedIntent)
        assertTrue(fixture.repository.recover(fixture.binding, pending, drop = false).isFailure)
        assertEquals(PendingMutationStatus.Failed.wireValue, fixture.dao.rows.getValue(id).status)
        assertOriginalIntent(unsupported, fixture.dao.rows.getValue(id))
        assertEquals(0, fixture.engine().drainOnce().attempted)
        assertTrue(fixture.api.calls.isEmpty())

        fixture.repository.recover(fixture.binding, pending, drop = true).getOrThrow()
        assertTrue(fixture.dao.rows.isEmpty())
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun zeroAmountOrBlankReasonCannotPublishOrSend() = runTest {
        for ((amountCents, reason) in listOf(0L to "  补记借款  ", 3_000L to "   ")) {
            val fixture = DebtAdjustmentFixture()
            val input = "amountCents=$amountCents, reason='$reason'"

            assertTrue(fixture.save(amountCents = amountCents, reason = reason).isFailure, input)

            assertTrue(fixture.dao.rows.isEmpty(), input)
            assertTrue(fixture.queueDepthAtSchedule.isEmpty(), input)
            assertTrue(fixture.api.calls.isEmpty(), input)
        }
    }

    @Test
    fun viewerCannotPublishOrRequeueAnOriginalAdjustment() = runTest {
        val viewer = DebtAdjustmentFixture(role = "viewer")
        assertTrue(viewer.save().isFailure)
        assertTrue(viewer.dao.rows.isEmpty())
        assertTrue(viewer.queueDepthAtSchedule.isEmpty())
        assertTrue(viewer.api.calls.isEmpty())

        val fixture = DebtAdjustmentFixture()
        val id = fixture.save().getOrThrow()
        fixture.outbox.markFailed(id, "debt_adjustment_response_unverified")
        val pending = fixture.pending()
        val original = fixture.dao.rows.getValue(id)
        fixture.session.switchLedgerForFixture("owner", "测试账本", "viewer")
        val viewerBinding = requireNotNull(fixture.repository.currentAccess()).binding

        assertTrue(fixture.repository.recover(viewerBinding, pending, drop = false).isFailure)

        assertEquals(original, fixture.dao.rows.getValue(id))
        assertEquals(listOf(1), fixture.queueDepthAtSchedule)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun changedBindingCannotPublishRecoverOrBorrowOriginalDetails() = runTest {
        val fixture = DebtAdjustmentFixture()
        val id = fixture.save().getOrThrow()
        fixture.outbox.markFailed(id, "debt_adjustment_response_unverified")
        val pending = fixture.pending()
        val original = fixture.dao.rows.getValue(id)
        fixture.session.switchLedgerForFixture("other", "另一账本")

        assertTrue(fixture.save().isFailure)
        assertTrue(fixture.repository.recover(fixture.binding, pending, drop = false).isFailure)
        assertNull(fixture.repository.describeAdjustment(pending.row))
        assertTrue(fixture.repository.observeAdjustments(fixture.binding, "d1").first().isEmpty())
        assertEquals(original, fixture.dao.rows.getValue(id))
        assertEquals(listOf(1), fixture.queueDepthAtSchedule)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun unresolvedOriginalIntentBlocksANewSaveForTheSameDebt() = runTest {
        for (status in listOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight,
            PendingMutationStatus.Conflict, PendingMutationStatus.Failed)) {
            val fixture = DebtAdjustmentFixture()
            val id = fixture.save().getOrThrow()
            val original = fixture.dao.rows.getValue(id).copy(status = status.wireValue)
            fixture.dao.rows[id] = original

            val refused = fixture.save(amountCents = 9_000L, reason = "另一次调整", debt = fixture.debt.copy(rowVersion = 9L))

            assertTrue(refused.isFailure, status.toString())
            assertEquals(listOf(original), fixture.dao.rows.values.toList())
            assertEquals(listOf(1), fixture.queueDepthAtSchedule)
            assertTrue(fixture.api.calls.isEmpty())
        }
    }
}

private fun assertOriginalIntent(expected: PendingMutationEntity, actual: PendingMutationEntity) {
    assertEquals(expected.id, actual.id)
    assertEquals(expected.type, actual.type)
    assertEquals(expected.targetId, actual.targetId)
    assertEquals(expected.ownerKey, actual.ownerKey)
    assertEquals(expected.ledgerId, actual.ledgerId)
    assertEquals(expected.serverUrl, actual.serverUrl)
    assertEquals(expected.payload, actual.payload)
    assertEquals(expected.idempotencyKey, actual.idempotencyKey)
    assertEquals(expected.expectedRowVersion, actual.expectedRowVersion)
    assertEquals(expected.createdAt, actual.createdAt)
}

internal class DebtAdjustmentFixture(role: String = "owner") {
    val session = TestSessionFixture().apply {
        saveToken("synthetic-session")
        if (role != "owner") switchLedgerForFixture("owner", "测试账本", role)
    }
    val api = DebtAdjustmentApiProbe()
    val provider = testApiServiceProvider(
        object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        },
        session,
    )
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val debt = adjustmentDebtDto().toDomain()
    val dao = FakePendingMutationDao()
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC)
    val queueDepthAtSchedule = mutableListOf<Int>()
    val adapters = OutboxAdapterGraph()
    val outbox = newOutbox(clock)
    val repository = newRepository(outbox)

    fun newOutbox(clock: Clock) = OutboxRepository(
        dao = dao,
        clock = clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() },
        onEnqueued = { queueDepthAtSchedule += dao.rows.size },
    )

    fun newRepository(outbox: OutboxRepository) = DebtAdjustmentRepository(provider, outbox, adapters.debtAdjustmentAdapter)

    suspend fun save(amountCents: Long = 3_000L, reason: String = "  补记借款  ", debt: Debt = this.debt) =
        repository.save(binding, debt, amountCents, reason)

    suspend fun pending() = repository.observeAdjustments(binding, debt.publicId).first().single()

    fun engine(outbox: OutboxRepository = this.outbox, clock: Clock = this.clock) = OutboxDrainEngine(
        outbox = outbox,
        dispatchers = listOf(RecordDebtAdjustmentDispatcher({ api }, adapters.debtAdjustmentAdapter)),
        now = clock::millis,
    )
}

internal data class AdjustmentCall(val publicId: String, val request: DebtAdjustmentCreateRequestDto, val idempotencyKey: String?)

internal class DebtAdjustmentApiProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<AdjustmentCall>()
    val facts = mutableMapOf<String, Pair<DebtAdjustmentCreateRequestDto, DebtDto>>()
    var loseResponse = false
    var refusal: Pair<Int, String>? = null
    private var rowVersion = 2L

    override suspend fun recordDebtAdjustment(
        publicId: String,
        request: DebtAdjustmentCreateRequestDto,
        idempotencyKey: String?,
    ): DebtDto {
        calls += AdjustmentCall(publicId, request, idempotencyKey)
        refusal?.let { (status, code) -> throw adjustmentRefusal(status, code) }
        val key = requireNotNull(idempotencyKey)
        // The backend checks an existing key before OCC; a fresh key with stale OCC is rejected.
        facts[key]?.let { (original, accepted) ->
            check(request == original) { "An existing adjustment key must keep its original body" }
            return accepted
        }
        if (request.expectedRowVersion != rowVersion) throw adjustmentRefusal(409, "state_conflict")
        rowVersion++
        val accepted = adjustmentDebtDto().copy(
            publicId = publicId,
            remainingAmountCents = 50_000L + request.amountCents,
            rowVersion = rowVersion,
        )
        facts[key] = request to accepted
        if (loseResponse) throw IOException("Synthetic response loss after adjustment commit")
        return accepted
    }
}

private fun adjustmentRefusal(status: Int, code: String) = HttpException(Response.error<DebtDto>(
    status,
    """{"error":"$code","message":"原调整未获确认"}""".toResponseBody("application/json".toMediaType()),
))

private fun adjustmentDebtDto() = DebtDto(
    publicId = "d1", ledgerId = "owner",
    direction = DebtDirections.I_OWE, counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyLabel = "房东", principalAmountCents = 50_000L, remainingAmountCents = 50_000L,
    paidAmountCents = 0L, status = "open", sourceType = DebtSourceTypes.MANUAL, homeCurrencyCode = "CNY",
    createdAt = "2026-09-06T00:00:00Z", updatedAt = "2026-09-06T00:00:00Z", rowVersion = 2L,
)
