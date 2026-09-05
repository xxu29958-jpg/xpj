package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtSourceTypes
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class DebtCreationRepositoryTest {
    @Test
    fun savePublishesCompleteIntentBeforeTheSchedulerAndNeverSendsDirectly() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()

        assertTrue(fixture.api.calls.isEmpty())
        assertEquals(listOf(1), fixture.queueDepthAtSchedule)
        val stored = fixture.dao.rows.getValue(receipt.intentId)
        val payload = requireNotNull(fixture.adapters.debtCreateAdapter.fromJson(stored.payload))
        assertEquals(fixture.binding, receipt.binding)
        assertEquals(fixture.binding.ownerKey, stored.ownerKey)
        assertEquals(fixture.binding.ledgerId, stored.ledgerId)
        assertEquals(fixture.binding.sessionGeneration, payload.originSessionGeneration)
        assertEquals(fixture.binding.bindingRevision, payload.originBindingRevision)
        assertEquals(1, payload.revision)
        assertEquals("CNY", payload.homeCurrencyCode)
        assertEquals(DebtDirections.OWED_TO_ME, payload.request.direction)
        assertEquals(DebtCounterpartyTypes.EXTERNAL, payload.request.counterpartyType)
        assertEquals(DebtSourceTypes.MANUAL, payload.request.sourceType)
        assertEquals("小王", payload.request.counterpartyLabel)
        assertEquals("出差垫付车费", payload.request.note)
        assertEquals(12_345L, payload.request.principalAmountCents)
        assertEquals(DebtKinds.INSTALLMENT, payload.request.debtKind)
        assertEquals(3L, payload.request.installmentCount)
        assertEquals(2L, payload.request.installmentPeriodMonths)
        assertTrue(stored.targetId.endsWith(requireNotNull(stored.idempotencyKey)))
        assertTrue(requireNotNull(stored.idempotencyKey).isNotBlank())
        assertEquals(PendingMutationStatus.Pending.wireValue, stored.status)
    }

    @Test
    fun lostResponseThenRestartedDrainReusesTheStoredRequestAndKey() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(receipt.intentId)

        val first = fixture.engine(fixture.outbox, fixture.clock).drainOnce()

        assertEquals(1, first.retryable)
        assertEquals(PendingMutationStatus.Pending.wireValue, fixture.dao.rows.getValue(receipt.intentId).status)
        assertEquals(original.payload, fixture.dao.rows.getValue(receipt.intentId).payload)
        val restartedClock = Clock.offset(fixture.clock, Duration.ofMinutes(2))
        val restartedOutbox = fixture.newOutbox(restartedClock)
        fixture.api.loseResponse = false
        val second = fixture.engine(restartedOutbox, restartedClock).drainOnce()

        assertEquals(1, second.done)
        assertEquals(2, fixture.api.calls.size)
        assertEquals(fixture.api.calls[0], fixture.api.calls[1])
        assertEquals(original.idempotencyKey, fixture.api.calls[1].second)
        assertEquals(1, fixture.api.facts.size)
        assertEquals(PendingMutationStatus.Done.wireValue, fixture.dao.rows.getValue(receipt.intentId).status)
    }

    @Test
    fun separateSaveIntentsKeepSeparateKeysEvenWhenTheValuesMatch() = runTest {
        val fixture = DebtCreationFixture()
        val first = fixture.save().getOrThrow()
        val second = fixture.save().getOrThrow()

        assertNotEquals(first.intentId, second.intentId)
        assertEquals(2, fixture.dao.rows.size)
        assertEquals(2, fixture.dao.rows.values.map { it.idempotencyKey }.toSet().size)
    }

    @Test
    fun viewerAndChangedBindingCannotPublishOrSend() = runTest {
        val viewer = DebtCreationFixture(role = "viewer")
        val refused = viewer.save()
        assertTrue(refused.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", refused.exceptionOrNull()?.message)
        assertTrue(viewer.dao.rows.isEmpty())
        assertTrue(viewer.api.calls.isEmpty())

        val switched = DebtCreationFixture()
        switched.session.switchLedgerForFixture("other", "另一账本")
        assertTrue(switched.save().isFailure)
        assertTrue(switched.dao.rows.isEmpty())
        assertTrue(switched.api.calls.isEmpty())
    }

    @Test
    fun invalidDraftsCannotPublishAndUntouchedKindRemainsUnspecified() = runTest {
        val fixture = DebtCreationFixture()
        val draft = DebtDraft(DebtDirections.I_OWE, "  房东  ", 50_000L)
        for (invalid in listOf(draft.copy(counterpartyLabel = "   "), draft.copy(principalAmountCents = 0L))) {
            val result = fixture.repository.createDebt(fixture.binding, invalid, CurrencyCode.CNY)
            assertTrue(result.isFailure)
            assertTrue(fixture.dao.rows.isEmpty())
            assertTrue(fixture.api.calls.isEmpty())
        }
        val receipt = fixture.repository.createDebt(fixture.binding, draft, CurrencyCode.CNY).getOrThrow()
        val payload = requireNotNull(fixture.adapters.debtCreateAdapter.fromJson(fixture.dao.rows.getValue(receipt.intentId).payload))
        assertEquals(DebtKinds.UNSPECIFIED, payload.request.debtKind)
        assertEquals("房东", payload.request.counterpartyLabel)
        assertEquals(50_000L, payload.request.principalAmountCents)
    }

    @Test
    fun unknownPayloadRevisionStaysRecoverableWithoutSendingOrChangingOriginalBytes() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()
        val row = fixture.dao.rows.getValue(receipt.intentId)
        val payload = requireNotNull(fixture.adapters.debtCreateAdapter.fromJson(row.payload))
        val unknown = row.copy(payload = fixture.adapters.debtCreateAdapter.toJson(payload.copy(revision = 99)))
        fixture.dao.rows[receipt.intentId] = unknown

        fixture.engine(fixture.outbox, fixture.clock).drainOnce()

        assertTrue(fixture.api.calls.isEmpty())
        val retained = fixture.dao.rows.getValue(receipt.intentId)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertEquals(unknown.payload, retained.payload)
        assertEquals(unknown.idempotencyKey, retained.idempotencyKey)
        val pending = fixture.repository.observePendingCreations().first { it.intents.isNotEmpty() }
        assertEquals(DebtCreationPendingState.Unsupported, pending.intents.single().state)
    }
}

internal class DebtCreationFixture(role: String = "owner") {
    val session = TestSessionFixture().apply {
        saveToken("synthetic-session")
        if (role != "owner") switchLedgerForFixture("owner", "测试账本", role)
    }
    val api = DebtCreationApiProbe()
    val provider = testApiServiceProvider(
        object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        },
        session,
    )
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val dao = FakePendingMutationDao()
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC)
    val queueDepthAtSchedule = mutableListOf<Int>()
    val outbox = newOutbox(clock)
    val adapters = OutboxAdapterGraph()
    val repository = DebtCreationRepository(provider, outbox, adapters.debtCreateAdapter)

    fun newOutbox(clock: Clock) = OutboxRepository(
        dao = dao,
        clock = clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() },
        onEnqueued = { queueDepthAtSchedule += dao.rows.size },
    )

    suspend fun save() = repository.createDebt(
        expectedBinding = binding,
        draft = DebtDraft(
            DebtDirections.OWED_TO_ME, " 小王 ", 12_345L,
            debtKind = DebtKinds.INSTALLMENT, installmentCount = 3, installmentPeriodMonths = 2,
            note = " 出差垫付车费 ",
        ),
        homeCurrency = CurrencyCode.CNY,
    )

    fun engine(outbox: OutboxRepository, clock: Clock) = OutboxDrainEngine(
        outbox = outbox,
        dispatchers = listOf(CreateDebtDispatcher({ api }, adapters.debtCreateAdapter)),
        now = clock::millis,
    )
}

internal class DebtCreationApiProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<Pair<DebtCreateRequestDto, String?>>()
    val facts = mutableMapOf<String, DebtDto>()
    var loseResponse = true

    override suspend fun createDebt(request: DebtCreateRequestDto, idempotencyKey: String?): DebtDto {
        calls += request to idempotencyKey
        val fact = facts.getOrPut(requireNotNull(idempotencyKey)) {
            DebtDto(
                publicId = "debt-${facts.size + 1}", ledgerId = "owner",
                direction = request.direction, counterpartyType = request.counterpartyType,
                counterpartyLabel = request.counterpartyLabel, principalAmountCents = request.principalAmountCents,
                remainingAmountCents = request.principalAmountCents, paidAmountCents = 0,
                status = "open", sourceType = request.sourceType, homeCurrencyCode = "CNY",
                createdAt = "2026-09-06T00:00:00Z", updatedAt = "2026-09-06T00:00:00Z", rowVersion = 1,
                debtKind = request.debtKind, installmentCount = request.installmentCount,
                installmentPeriodMonths = request.installmentPeriodMonths, note = request.note,
            )
        }
        if (loseResponse) throw IOException("Synthetic response loss after acceptance")
        return fact
    }
}
