package com.ticketbox.data.repository

import com.ticketbox.domain.model.ExpenseHistorySnapshot

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
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

internal class ExpenseOffsetRepositoryTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun coldHistoryPagesKeepTheirOriginalAnchorAndNeverBorrowPagesFromANewerRevision() = runTest {
        var offline = false
        var latest = 51L
        val dao = FakeExpenseDao()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun expenseRevisions(id: Long, page: Int, pageSize: Int, snapshotRevision: Long?, offsetSnapshotId: Long?):
                com.ticketbox.data.remote.dto.ExpenseRevisionPageDto {
                if (offline) throw java.net.ConnectException("offline")
                val anchor = snapshotRevision ?: latest
                val numbers = (anchor downTo 1).drop((page - 1) * pageSize).take(pageSize)
                return com.ticketbox.data.remote.dto.ExpenseRevisionPageDto(numbers.map { revision ->
                    com.ticketbox.data.remote.dto.ExpenseRevisionDto("revision-$revision", revision, "corrected", "核对 $revision",
                        listOf("note"), after = mapOf("note" to "历史 $revision"), createdAt = "2026-09-30T00:00:00Z")
                }, page, pageSize, anchor.toInt(), anchor, offsetSnapshotId = 0)
            }
        }
        val original = buildRepository(api, dao)
        val first = original.fetchExpenseRevisions(9).getOrThrow()
        val older = original.fetchExpenseRevisions(9, 2, 50, ExpenseHistorySnapshot(first.value.snapshotRevision, first.value.offsetSnapshotId)).getOrThrow()
        offline = true
        val reopened = buildRepository(api, dao)
        val restored = reopened.fetchExpenseRevisions(9).getOrThrow()
        assertTrue(restored.fromCache)
        assertEquals(first.value, restored.value)
        assertEquals(older.value, reopened.fetchExpenseRevisions(9, 2, 50, ExpenseHistorySnapshot(restored.value.snapshotRevision, restored.value.offsetSnapshotId)).getOrThrow().value)
        assertEquals(51, (restored.value.items + older.value.items).map { it.publicId }.toSet().size)
        assertTrue(reopened.fetchExpenseRevisions(10).isFailure)
        offline = false
        latest = 52
        assertEquals(52L, reopened.fetchExpenseRevisions(9).getOrThrow().value.snapshotRevision)
        offline = true
        assertTrue(buildRepository(api, dao).fetchExpenseRevisions(9, 2, 50, ExpenseHistorySnapshot(52, 0)).isFailure,
            "An unread page from the new snapshot must not be filled from the old prefix")
    }

    @Test
    fun refusedFactReadRetiresKnownHistoryInsteadOfReopeningItAsOfflineSuccess() = runTest {
        for (status in listOf(403, 404)) {
            var failure: Throwable? = null
            val dao = FakeExpenseDao()
            val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
                override suspend fun expenseFactBundle(id: String): ExpenseFactBundleDto {
                    failure?.let { throw it }
                    return expenseFactBundleDtoFixture()
                }
            }
            val repository = buildRepository(api, dao)
            repository.fetchExpenseFactBundle(9).getOrThrow()
            failure = retrofit2.HttpException(retrofit2.Response.error<Any>(status,
                okhttp3.ResponseBody.create(null, "")))
            assertTrue(repository.fetchExpenseFactBundle(9).isFailure)
            assertTrue(repository.fetchExpenseFromLocalCache(9).isFailure,
                "A known $status must also retire the fact page's independent root-cache entry")
            failure = java.net.ConnectException("offline")
            assertTrue(buildRepository(api, dao).fetchExpenseFactBundle(9).isFailure)
        }
    }

    @Test
    fun anOldResponseCannotRepopulateHistoryAfterTheFactWasRefused() = runTest {
        val started = kotlinx.coroutines.CompletableDeferred<Unit>()
        val release = kotlinx.coroutines.CompletableDeferred<Unit>()
        var calls = 0
        val dao = FakeExpenseDao()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun expenseFactBundle(id: String): ExpenseFactBundleDto {
                when (++calls) {
                    1 -> { started.complete(Unit); release.await() }
                    2 -> throw retrofit2.HttpException(retrofit2.Response.error<Any>(404, okhttp3.ResponseBody.create(null, "")))
                    else -> throw java.net.ConnectException("offline")
                }
                return expenseFactBundleDtoFixture()
            }
        }
        val repository = buildRepository(api, dao)
        val old = async { repository.fetchExpenseFactBundle(9) }
        started.await()
        assertTrue(repository.fetchExpenseFactBundle(9).isFailure)
        release.complete(Unit)
        assertTrue(old.await().isFailure)
        assertTrue(buildRepository(api, dao).fetchExpenseFactBundle(9).isFailure)
    }

    @Test
    fun reopeningOfflineRetainsThePreviouslyReadRefundHistory() = runTest {
        val dao = FakeExpenseDao()
        val dto = expenseFactBundleDtoFixture()
        val online = OffsetApiService(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0), createResponse = dto)
        val known = buildRepository(online, dao).fetchExpenseFactBundle(9).getOrThrow()
        val offline = object : ApiService by online {
            override suspend fun expenseFactBundle(id: String): ExpenseFactBundleDto = throw java.net.UnknownHostException("offline")
        }

        val reopened = buildRepository(offline, dao).fetchExpenseFactBundle(9).getOrThrow()

        assertEquals(known.value, reopened.value, "A new repository must read known refund history from persistent storage")
        assertTrue(reopened.fromCache)
        assertEquals(known.fetchedAt, reopened.fetchedAt)
        assertEquals("refund-1", reopened.value.activeOffsets.single().publicId)
    }

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

        repeat(2) { assertEquals(bundle.toDomain(), repository.fetchExpenseFactBundle(9).getOrThrow().value) }

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

        patchExpenseAdapter = com.ticketbox.OutboxAdapterGraph().patchExpenseAdapter,
        expenseStateTokenAdapter = com.ticketbox.OutboxAdapterGraph().expenseStateTokenAdapter,
        recognizeTextAdapter = com.ticketbox.OutboxAdapterGraph().recognizeTextAdapter,
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
