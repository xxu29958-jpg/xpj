package com.ticketbox.data.repository

import com.ticketbox.domain.model.ExpenseTimeInput
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
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class DebtCreationRepositoryTest {
    @Test fun returnToLedgerReusesExactSourceCreateBytesAndRejectsChangedBody() = runTest {
        val fixture = DebtCreationFixture()
        val draft = DebtDraft(DebtDirections.I_OWE, "原账单", 1234L,
            billSource = com.ticketbox.data.remote.dto.DebtBillSourceReferenceDto("original-source", 7L),
            timeInput = ExpenseTimeInput("date_only", userLocalDate = "2026-01-31", calendarRevision = 3L))
        val first = fixture.repository.createDebt(fixture.binding, draft, CurrencyCode.CNY, "original-source-create").getOrThrow()
        val stored = fixture.dao.rows.getValue(first.intentId)
        val exact = stored.copy(payload = " \n${stored.payload}\n ")
        fixture.dao.rows[first.intentId] = exact
        fixture.session.switchLedgerForFixture("other", "另一账本")
        fixture.session.switchLedgerForFixture(fixture.binding.ledgerId, "返回账本")
        val rebound = requireNotNull(fixture.repository.currentAccess()).binding
        assertNotEquals(fixture.binding.bindingRevision, rebound.bindingRevision)
        val replay = fixture.repository.createDebt(rebound, draft, CurrencyCode.CNY, "original-source-create").getOrThrow()
        assertEquals(first.intentId, replay.intentId)
        assertEquals(exact, fixture.dao.rows.getValue(first.intentId))
        assertEquals(1, fixture.dao.rows.size)
        for (changed in listOf(draft.copy(principalAmountCents = 1235L),
            draft.copy(billSource = draft.billSource?.copy(expectedRowVersion = 8L)))) {
            assertTrue(fixture.repository.createDebt(rebound, changed, CurrencyCode.CNY, "original-source-create").isFailure)
            assertEquals(exact, fixture.dao.rows.getValue(first.intentId))
        }
        val unknown = exact.copy(payload = exact.payload.replace("\"revision\":2", "\"revision\":99"))
        fixture.dao.rows[first.intentId] = unknown
        assertTrue(fixture.repository.createDebt(rebound, draft, CurrencyCode.CNY, "original-source-create").isFailure)
        assertEquals(unknown, fixture.dao.rows.getValue(first.intentId))
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun savePublishesCompleteIntentBeforeTheSchedulerAndNeverSendsDirectly() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()

        assertTrue(fixture.api.calls.isEmpty())
        assertEquals(listOf(1), fixture.queueDepthAtSchedule)
        val stored = fixture.dao.rows.getValue(receipt.intentId)
        val payload = requireNotNull(fixture.adapters.debt.debtCreateAdapter.fromJson(stored.payload))
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
    fun aStoredV1IntentSuppliesItsCurrencyToTheNewWireRequest() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()
        val row = fixture.dao.rows.getValue(receipt.intentId)
        // This is the released Room shape: the nested request has no currency field.
        val original = """{
            "revision":1,"homeCurrencyCode":"JPY",
            "originSessionGeneration":"${fixture.binding.sessionGeneration}",
            "originBindingRevision":"${fixture.binding.bindingRevision}",
            "request":{"direction":"owed_to_me","counterparty_type":"external",
                "counterparty_label":"Alex","principal_amount_cents":1200,
                "source_type":"manual","debt_kind":"unspecified"}
        }"""
        fixture.dao.rows[row.id] = row.copy(payload = original)

        fixture.api.response = fixture.api.response.copy(homeCurrencyCode = "JPY", counterpartyLabel = "Alex",
            principalAmountCents = 1200, remainingAmountCents = 1200, debtKind = "unspecified",
            installmentCount = null, installmentPeriodMonths = null, note = null)

        fixture.dao.runnableBatches += listOf(receipt.intentId)
        fixture.engine(fixture.outbox, fixture.clock).drainOnce()

        val sent = fixture.api.calls.single()
        assertEquals("JPY", sent.first.homeCurrencyCode)
        assertEquals(1200L, sent.first.principalAmountCents)
        assertEquals(row.idempotencyKey, sent.second)
        assertEquals(original, fixture.dao.rows.getValue(row.id).payload)
        assertEquals(null, sent.first.timeInput)
        assertEquals(null, sent.first.billSource)
        assertTrue(!com.squareup.moshi.Moshi.Builder().build().adapter(DebtCreateRequestDto::class.java)
            .toJson(sent.first).contains("bill_source"), "Released no-source bodies must omit the new optional field")
        assertEquals(PendingMutationStatus.Done.wireValue, fixture.dao.rows.getValue(row.id).status)
    }

    @Test
    fun aReceiptWithAnotherCurrencyDoesNotSettleTheOriginalIntent() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(receipt.intentId)

        fixture.api.response = fixture.api.response.copy(homeCurrencyCode = "JPY")

        fixture.dao.runnableBatches += listOf(receipt.intentId)
        fixture.engine(fixture.outbox, fixture.clock).drainOnce()

        val retained = fixture.dao.rows.getValue(receipt.intentId)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertEquals(original.payload, retained.payload)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
    }

    @Test
    fun aReceiptWithAnotherDateKeepsTheOriginalKeyAndInput() = runTest {
        val fixture = DebtCreationFixture()
        val time = com.ticketbox.domain.model.ExpenseTimeInput("date_only", 3L, "2026-01-31")
        val receipt = fixture.save(time).getOrThrow()
        val original = fixture.dao.rows.getValue(receipt.intentId)

        fixture.api.response = fixture.api.response.copy(accountingTime = com.ticketbox.data.remote.dto.ExpenseAccountingTimeDto(
            precision = "date_only", userLocalDate = "2026-02-01", calendarRevision = 3))
        fixture.dao.runnableBatches += listOf(receipt.intentId)
        fixture.engine(fixture.outbox, fixture.clock).drainOnce()
        val retained = fixture.dao.rows.getValue(receipt.intentId)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertEquals(original.payload, retained.payload)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
    }

    @Test
    fun anotherCreationReceiptCannotSettleTheOriginalTerms() = runTest {
        val mismatches: List<(DebtDto) -> DebtDto> = listOf(
            { it.copy(principalAmountCents = 1) }, { it.copy(direction = DebtDirections.I_OWE) },
            { it.copy(counterpartyLabel = "另一位") }, { it.copy(counterpartyType = "member") },
            { it.copy(sourceType = "bill_split") }, { it.copy(note = "另一用途") },
            { it.copy(debtKind = "one_off") }, { it.copy(installmentCount = 9) },
            { it.copy(installmentPeriodMonths = 9) },
        )
        for (mismatch in mismatches) {
            val fixture = DebtCreationFixture()
            val receipt = fixture.save().getOrThrow()
            val original = fixture.dao.rows.getValue(receipt.intentId)

            fixture.api.response = mismatch(fixture.api.response)
            fixture.dao.runnableBatches += listOf(receipt.intentId)
            fixture.engine(fixture.outbox, fixture.clock).drainOnce()
            val retained = fixture.dao.rows.getValue(receipt.intentId)
            assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
            assertEquals(original.payload, retained.payload)
            assertEquals(original.idempotencyKey, retained.idempotencyKey)
        }
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
            val result = fixture.repository.createDebt(fixture.binding, invalid, CurrencyCode.CNY, "invalid-draft")
            assertTrue(result.isFailure)
            assertTrue(fixture.dao.rows.isEmpty())
            assertTrue(fixture.api.calls.isEmpty())
        }
        val receipt = fixture.repository.createDebt(fixture.binding, draft, CurrencyCode.CNY, "valid-draft").getOrThrow()
        val payload = requireNotNull(fixture.adapters.debt.debtCreateAdapter.fromJson(fixture.dao.rows.getValue(receipt.intentId).payload))
        assertEquals(DebtKinds.UNSPECIFIED, payload.request.debtKind)
        assertEquals("房东", payload.request.counterpartyLabel)
        assertEquals(50_000L, payload.request.principalAmountCents)
    }

    @Test
    fun unknownPayloadRevisionStaysRecoverableWithoutSendingOrChangingOriginalBytes() = runTest {
        val fixture = DebtCreationFixture()
        val receipt = fixture.save().getOrThrow()
        val row = fixture.dao.rows.getValue(receipt.intentId)
        val payload = requireNotNull(fixture.adapters.debt.debtCreateAdapter.fromJson(row.payload))
        val unknown = row.copy(payload = fixture.adapters.debt.debtCreateAdapter.toJson(payload.copy(revision = 99)))
        fixture.dao.rows[receipt.intentId] = unknown

        fixture.dao.runnableBatches += listOf(receipt.intentId)
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
    val outbox = OutboxRepository(
        onRowsDeleted = {},
        dao = dao,
        clock = clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() },
        onEnqueued = { queueDepthAtSchedule += dao.rows.size },
    )
    val adapters = OutboxAdapterGraph()
    val repository = DebtCreationRepository(provider, outbox, adapters.debt.debtCreateAdapter)

    suspend fun save(time: com.ticketbox.domain.model.ExpenseTimeInput? = null,
        creationKey: String = java.util.UUID.randomUUID().toString()) = repository.createDebt(
        expectedBinding = binding,
        draft = DebtDraft(
            DebtDirections.OWED_TO_ME, " 小王 ", 12_345L,
            debtKind = DebtKinds.INSTALLMENT, installmentCount = 3, installmentPeriodMonths = 2,
            note = " 出差垫付车费 ",
            timeInput = time,
        ),
        homeCurrency = CurrencyCode.CNY,
        creationKey = creationKey,
    )

    fun engine(outbox: OutboxRepository, clock: Clock) = OutboxDrainEngine(
        outbox = outbox,
        dispatchers = listOf(CreateDebtDispatcher({ api }, adapters.debt.debtCreateAdapter)),
        now = clock::millis,
    )
}

internal class DebtCreationApiProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<Pair<DebtCreateRequestDto, String?>>()
    var response = DebtDto(publicId = "debt-1", ledgerId = "owner", direction = "owed_to_me", counterpartyType = "external",
        counterpartyLabel = "小王", principalAmountCents = 12_345, remainingAmountCents = 12_345, paidAmountCents = 0,
        status = "open", sourceType = "manual", homeCurrencyCode = "CNY", createdAt = "2026-09-06T00:00:00Z",
        updatedAt = "2026-09-06T00:00:00Z", rowVersion = 1, debtKind = "installment", installmentCount = 3,
        installmentPeriodMonths = 2, note = "出差垫付车费")

    override suspend fun createDebt(request: DebtCreateRequestDto, idempotencyKey: String?): DebtDto {
        calls += request to idempotencyKey
        return response
    }
}
