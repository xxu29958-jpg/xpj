package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.ExpenseOffsetStatus
import com.ticketbox.domain.model.StreamOffsetKind
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.flow.first
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

internal class ExpenseOffsetRepositoryTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun persistedRefundBlocksCurrencyCorrectionAndCannotBeRebasedByTokenPropagation() = runTest {
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = mutationDao)
        val api = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val repository = buildRepository(api, FakeExpenseDao(), outbox)
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val root = rootExpense(7).copy(originalAmountMinor = 10_000L,
            originalCurrencyCode = CurrencyCode.CNY, originalCurrencyCodeRaw = "CNY")

        assertIs<ExpenseOffsetMutationOutcome.Queued>(repository.createExpenseOffsetAllowingOffline(binding, root,
            ExpenseOffsetDraft(StreamOffsetKind.Refund, 1_000L, "2026-09-03", "Original CNY refund")).getOrThrow())
        val original = mutationDao.rows.values.single()
        assertEquals(null, api.createRequest)
        assertTrue(repository.submitCorrection(binding, root,
            ExpenseCorrectionDraft("The receipt is in yen", originalCurrencyCode = CurrencyCode.JPY,
                originalAmountMinor = 1_000L)).isFailure)

        outbox.cascadeFreshToken(original.targetId, 8L)
        assertEquals(listOf(original), mutationDao.rows.values.toList(),
            "The original currency-basis OCC, body, binding and key survive subsequent read/token propagation")
    }

    @Test
    fun currencyCorrectionRefusesANewOffsetWithoutChangingTheOriginalIntent() = runTest {
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = mutationDao)
        val api = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val repository = buildRepository(api, FakeExpenseDao(), outbox)
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val root = rootExpense(rowVersion = 7).copy(originalAmountMinor = 10_000L,
            originalCurrencyCode = CurrencyCode.CNY, originalCurrencyCodeRaw = "CNY")
        repository.submitCorrection(binding, root,
            ExpenseCorrectionDraft("The receipt is in yen", originalCurrencyCode = CurrencyCode.JPY,
                originalAmountMinor = 1_000L)).getOrThrow()
        val original = mutationDao.rows.values.single()
        assertEquals(PendingMutationType.CorrectExpense.wireValue, original.type)
        assertEquals(7L, original.expectedRowVersion)

        val result = repository.createExpenseOffsetAllowingOffline(binding, root,
            ExpenseOffsetDraft(StreamOffsetKind.Refund, 1_000L, "2026-09-03", "Refund in original currency"))

        assertTrue(result.isFailure)
        assertEquals(listOf(original), mutationDao.rows.values.toList())
        assertEquals(null, api.createRequest)
        assertEquals(null, api.idempotencyKey)
    }

    @Test
    fun aRetiredBindingCannotCreateAnOffsetInTheCurrentLedger() = runTest {
        val mutationDao = FakePendingMutationDao()
        val api = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val repository = buildRepository(api, FakeExpenseDao(), testOutboxRepository(mutationDao))
        val current = requireNotNull(repository.observeCorrections().first().access).binding

        val result = repository.createExpenseOffsetAllowingOffline(
            current.copy(bindingRevision = "retired-binding"), rootExpense(rowVersion = 7),
            ExpenseOffsetDraft(StreamOffsetKind.Refund, 1_000L, "2026-09-03", "Original refund"))

        assertTrue(result.isFailure)
        assertTrue(mutationDao.rows.isEmpty())
        assertEquals(null, api.createRequest)
        assertEquals(null, api.idempotencyKey)
    }

    @Test
    fun aRetiredBindingCannotQueueAVoidInTheCurrentLedger() = runTest {
        val mutationDao = FakePendingMutationDao()
        val api = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val repository = buildRepository(api, FakeExpenseDao(), testOutboxRepository(mutationDao))
        val current = requireNotNull(repository.observeCorrections().first().access).binding

        val result = repository.voidExpenseOffsetAllowingOffline(
            current.copy(bindingRevision = "retired-binding"), rootExpense(rowVersion = 7),
            offsetFact(rowVersion = 2), "Original ledger void")

        assertTrue(result.isFailure)
        assertTrue(mutationDao.rows.isEmpty())
        assertEquals(null, api.voidRequest)
        assertEquals(null, api.idempotencyKey)
    }

    @Test
    fun queuedRefundLosingItsAckReplaysOriginalThroughDispatcherAndEngineOnlyOnce() = runTest {
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(mutationDao)
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(9, "root-9", "高德").copy(rowVersion = 3,
            streamDate = "2026-05-07", streamAmountCents = 1_200, lineageStatus = "confirmed",
            lineageHomeNetCents = 1_200))
        val receipt = expenseFactBundleDtoFixture(root = confirmedExpenseDtoFixture(
            ConfirmedExpenseFixture(amountCents = 1_200, rowVersion = 4)))
        val requests = mutableListOf<Pair<ExpenseOffsetCreateRequestDto, String>>()
        val accepted = mutableMapOf<String, ExpenseFactBundleDto>()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun createExpenseOffset(
                id: String, request: ExpenseOffsetCreateRequestDto, idempotencyKey: String,
            ): ExpenseFactBundleDto {
                val original = mutationDao.rows.values.single()
                assertEquals(PendingMutationStatus.InFlight.wireValue, original.status)
                assertEquals(idempotencyKey, original.idempotencyKey)
                requests += request to idempotencyKey
                val result = accepted.getOrPut(idempotencyKey) { receipt }
                if (requests.size == 1) throw IOException("accepted, but response lost")
                return result
            }
        }
        val repository = buildRepository(api, dao, outbox)
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        assertIs<ExpenseOffsetMutationOutcome.Queued>(repository.createExpenseOffsetAllowingOffline(binding,
            rootExpense(3), ExpenseOffsetDraft(StreamOffsetKind.Refund, 300, "2026-09-03", "退款到账")).getOrThrow())
        val original = mutationDao.rows.values.single()
        assertTrue(requests.isEmpty())
        assertEquals(binding.ownerKey, original.ownerKey)
        assertEquals(binding.ledgerId, original.ledgerId)
        assertEquals(binding.serverUrl, original.serverUrl)
        val dispatcher = CreateExpenseOffsetDispatcher({ api },
            moshi().adapter(ExpenseOffsetCreateRequestDto::class.java), { ledger, dto ->
                val projection = dto.toCacheProjection(ledger)
                dao.applyExpenseFactBundle(ledger, projection.root, projection.activeOffsets)
            })
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))

        assertEquals(1, engine.drainOnce().retryable)
        assertEquals(1, accepted.size)
        assertTrue(dao.getConfirmedStreamOffsets("owner").isEmpty())
        assertEquals(0L, outbox.acceptedReplayRevision.value)
        assertEquals(original.payload, mutationDao.rows.getValue(original.id).payload)
        assertEquals(1, engine.drainOnce().done)
        assertEquals(2, requests.size)
        assertEquals(requests[0], requests[1])
        assertEquals(original.idempotencyKey, requests[1].second)
        assertEquals(3L, requests[1].first.expectedRowVersion)
        assertEquals(300L, requests[1].first.originalAmountMinor)
        assertEquals("2026-09-03", requests[1].first.accountingDate)
        assertEquals(1, accepted.size)
        assertEquals(1L, outbox.acceptedReplayRevision.value)
        assertEquals("refund-1", dao.getConfirmedStreamOffsets("owner").single().publicId)
        val cached = assertNotNull(dao.findByServerId("owner", 9))
        assertEquals("2026-05-07", cached.streamDate)
        assertEquals(1_200L, cached.streamAmountCents)
        assertEquals(PendingMutationStatus.Done.wireValue, mutationDao.rows.getValue(original.id).status)
    }

    @Test
    fun repeatedAuthoritativeBundleReadsUpdateCacheWithoutPublishingWriteSignals() = runTest {
        val dao = FakeExpenseDao()
        val bundle = expenseFactBundleDtoFixture()
        val api = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0), createResponse = bundle)
        val repository = buildRepository(api, dao)
        var writes = 0
        repository.onConfirmedCommitted = { writes += 1 }

        repeat(2) { assertEquals(bundle.toDomain(), repository.fetchExpenseFactBundle(9).getOrThrow()) }

        assertEquals(0, writes)
        assertNotNull(dao.findByServerId("owner", 9))
        assertEquals("refund-1", dao.getConfirmedStreamOffsets("owner").single().publicId)
    }

    @Test
    fun refundPersistsOriginalPayloadBeforeAnyHttpAndCreatesNoPhantomStreamRow() = runTest {
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = mutationDao)
        val dao = FakeExpenseDao()
        val api = OffsetApiService(
            FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            failure = IOException("offline"),
        )
        val repository = buildRepository(api, dao, outbox)

        val outcome = repository.createExpenseOffsetAllowingOffline(
            requireNotNull(repository.observeCorrections().first().access).binding,
            rootExpense(rowVersion = 7),
            ExpenseOffsetDraft(StreamOffsetKind.Chargeback, 300, "2026-09-03", "拒付"),
        ).getOrThrow()

        assertIs<ExpenseOffsetMutationOutcome.Queued>(outcome)
        assertTrue(dao.getConfirmedStreamOffsets("owner").isEmpty())
        val row = mutationDao.rows.values.single()
        assertEquals(PendingMutationType.CreateExpenseOffset.wireValue, row.type)
        assertEquals("expense:9", row.targetId)
        assertEquals(7L, row.expectedRowVersion)
        assertEquals(null, api.idempotencyKey)
        assertEquals(null, api.createRequest)
        assertTrue(!row.idempotencyKey.isNullOrBlank())
        val originalRequest = moshi().adapter(ExpenseOffsetCreateRequestDto::class.java).fromJson(row.payload)
        assertEquals(ExpenseOffsetCreateRequestDto(com.ticketbox.data.remote.dto.ExpenseOffsetKindDto.Chargeback,
            300, "2026-09-03", "拒付", 7), originalRequest)
        assertEquals(7L, originalRequest?.expectedRowVersion)
    }

    @Test
    fun queuedVoidUsesOffsetOccAndKeepsTheFactUntilDispatcherAcceptance() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(9, "root-9", "高德"))
        dao.upsertConfirmedStreamOffsets(listOf(cachedOffsetEntity()))
        val api = OffsetApiService(
            FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            voidResponse = expenseFactBundleDtoFixture(
                status = com.ticketbox.data.remote.dto.ExpenseLineageStatusDto.Confirmed,
                lineageHomeNetCents = 1_200,
                activeOffsets = emptyList(),
            ),
        )
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(mutationDao)
        val repository = buildRepository(api, dao, outbox)

        val outcome = repository.voidExpenseOffsetAllowingOffline(
            requireNotNull(repository.observeCorrections().first().access).binding,
            rootExpense(rowVersion = 3),
            offsetFact(rowVersion = 2),
            "误记退款",
        ).getOrThrow()

        assertIs<ExpenseOffsetMutationOutcome.Queued>(outcome)
        assertEquals(null, api.voidRequest)
        assertEquals(1, dao.getConfirmedStreamOffsets("owner").size)
        val original = mutationDao.rows.values.single()
        assertEquals(2L, original.expectedRowVersion)
        val dispatcher = VoidExpenseOffsetDispatcher({ api },
            moshi().adapter(ExpenseOffsetVoidOutboxPayload::class.java), { ledger, dto ->
                val projection = dto.toCacheProjection(ledger)
                dao.applyExpenseFactBundle(ledger, projection.root, projection.activeOffsets)
            })
        assertEquals(1, OutboxDrainEngine(outbox, listOf(dispatcher)).drainOnce().done)
        assertEquals(original.idempotencyKey, api.idempotencyKey)
        assertEquals(2L, api.voidRequest?.expectedRowVersion)
        assertTrue(dao.getConfirmedStreamOffsets("owner").isEmpty())
    }

    @Test
    fun voidPersistsOriginalIdentityBeforeAnyHttp() = runTest {
        val mutationDao = FakePendingMutationDao()
        val api = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            failure = IOException("offline"))
        val repository = buildRepository(
            api = api,
            dao = FakeExpenseDao(),
            outbox = testOutboxRepository(dao = mutationDao),
        )

        val outcome = repository.voidExpenseOffsetAllowingOffline(
            requireNotNull(repository.observeCorrections().first().access).binding,
            rootExpense(rowVersion = 7),
            offsetFact(rowVersion = 2),
            "误记退款",
        ).getOrThrow()

        assertIs<ExpenseOffsetMutationOutcome.Queued>(outcome)
        assertEquals(null, api.voidRequest)
        assertEquals(null, api.idempotencyKey)
        val row = mutationDao.rows.values.single()
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        assertEquals(binding.ownerKey, row.ownerKey)
        assertEquals(binding.ledgerId, row.ledgerId)
        assertEquals(binding.serverUrl, row.serverUrl)
        assertTrue(!row.idempotencyKey.isNullOrBlank())
        assertEquals("expense:9", row.targetId)
        assertEquals(2L, row.expectedRowVersion)
        assertTrue("\"offset_public_id\":\"refund-1\"" in row.payload, row.payload)
        assertTrue("\"void_reason\":\"误记退款\"" in row.payload, row.payload)
    }

    private fun buildRepository(
        api: ApiService,
        dao: FakeExpenseDao,
        outbox: OutboxRepository? = null,
    ) = ExpenseRepository(
        expenseDao = dao,
        binding = testServerSessionBinding(
            apiClient = TestApiServiceFactory(api),
            settingsStore = seededSettingsStore(),
            tokenStore = seededTokenStore(),
        ),
        offlineMutations = ExpenseOfflineMutationWiring(
            outbox = outbox ?: testOutboxRepository(FakePendingMutationDao()),
            offsetCreateAdapter = moshi().adapter(ExpenseOffsetCreateRequestDto::class.java),
            offsetVoidAdapter = moshi().adapter(ExpenseOffsetVoidOutboxPayload::class.java),
            correctionAdapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            billSplitReceiptAdapter = com.ticketbox.OutboxAdapterGraph().billSplitReceiptAdapter,
            billSplitCreateAdapter = com.ticketbox.OutboxAdapterGraph().billSplitCreateAdapter,
            legacyCorrectionAdapter = com.ticketbox.OutboxAdapterGraph().legacyCorrectionAdapter,
            manualCreateAdapter = com.ticketbox.OutboxAdapterGraph().manualCreateAdapter,
        ),
    )

    private fun rootExpense(rowVersion: Long) = baselineExpense().copy(
        id = 9,
        status = "confirmed",
        rowVersion = rowVersion,
        pendingSync = false,
    )

    private fun offsetFact(rowVersion: Long) = ExpenseOffsetFact(
        publicId = "refund-1",
        kind = StreamOffsetKind.Refund,
        status = ExpenseOffsetStatus.Active,
        originalCurrencyCode = "CNY",
        originalAmountMinor = 300,
        homeCurrencyCode = "CNY",
        amountCents = 300,
        streamAmountCents = -300,
        accountingDate = "2026-09-03",
        category = "交通",
        reason = "退款到账",
        rowVersion = rowVersion,
        factRevision = 1,
        createdAt = "2026-09-03T04:00:00Z",
        updatedAt = "2026-09-03T04:00:00Z",
    )

    private fun cachedOffsetEntity() = expenseFactBundleDtoFixture()
        .toCacheProjection("owner")
        .activeOffsets
        .single()

    private class OffsetApiService(
        private val delegate: ApiService,
        private val createResponse: ExpenseFactBundleDto? = null,
        private val voidResponse: ExpenseFactBundleDto? = null,
        private val failure: Throwable? = null,
    ) : ApiService by delegate {
        var createRequest: ExpenseOffsetCreateRequestDto? = null
        var voidRequest: ExpenseOffsetVoidRequestDto? = null
        var idempotencyKey: String? = null

        override suspend fun expenseFactBundle(id: String): ExpenseFactBundleDto = requireNotNull(createResponse)

        override suspend fun createExpenseOffset(
            id: String,
            request: ExpenseOffsetCreateRequestDto,
            idempotencyKey: String,
        ): ExpenseFactBundleDto {
            createRequest = request
            this.idempotencyKey = idempotencyKey
            failure?.let { throw it }
            return requireNotNull(createResponse)
        }

        override suspend fun voidExpenseOffset(
            id: String,
            offsetPublicId: String,
            request: ExpenseOffsetVoidRequestDto,
            idempotencyKey: String,
        ): ExpenseFactBundleDto {
            voidRequest = request
            this.idempotencyKey = idempotencyKey
            failure?.let { throw it }
            return requireNotNull(voidResponse)
        }
    }
}
