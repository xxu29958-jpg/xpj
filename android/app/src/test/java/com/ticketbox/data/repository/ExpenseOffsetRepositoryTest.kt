package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.ExpenseOffsetStatus
import com.ticketbox.domain.model.StreamOffsetKind
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

internal class ExpenseOffsetRepositoryTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun currencyCorrectionDuringLostRefundResponseCannotRebaseTheOriginalRefund() = runTest {
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = mutationDao)
        val entered = CompletableDeferred<Pair<ExpenseOffsetCreateRequestDto, String>>()
        val release = CompletableDeferred<Unit>()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun createExpenseOffset(
                id: String, request: ExpenseOffsetCreateRequestDto, idempotencyKey: String,
            ): ExpenseFactBundleDto {
                entered.complete(request to idempotencyKey)
                release.await()
                throw IOException("response unavailable")
            }
        }
        val repository = buildRepository(api, FakeExpenseDao(), outbox)
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val root = rootExpense(7).copy(originalAmountMinor = 10_000L,
            originalCurrencyCode = CurrencyCode.CNY, originalCurrencyCodeRaw = "CNY")
        val attempt = async(start = CoroutineStart.UNDISPATCHED) {
            repository.createExpenseOffsetAllowingOffline(binding, root,
                ExpenseOffsetDraft(StreamOffsetKind.Refund, 1_000L, "2026-09-03", "Original CNY refund"))
        }
        try {
            val (sentRequest, sentKey) = entered.await()
            assertTrue(mutationDao.rows.isEmpty(), "the initial request is in flight before fallback persistence")
            repository.submitCorrection(binding, root,
                ExpenseCorrectionDraft("The receipt is in yen", originalCurrencyCode = CurrencyCode.JPY,
                    originalAmountMinor = 1_000L)).getOrThrow()
            val correction = mutationDao.rows.values.single()
            release.complete(Unit)
            assertIs<ExpenseOffsetMutationOutcome.Queued>(attempt.await().getOrThrow())
            val refund = mutationDao.rows.values.single { it.type == PendingMutationType.CreateExpenseOffset.wireValue }
            assertEquals(sentKey, refund.idempotencyKey)
            assertEquals(sentRequest.expectedRowVersion, refund.expectedRowVersion)
            assertTrue(correction.id < refund.id, "the accepted correction precedes the fallback refund")
            assertEquals(correction, mutationDao.rows.getValue(correction.id))

            // Exercise the actual completion consumer; no test-local token rewrite.
            outbox.cascadeFreshToken(correction.targetId, 8L)

            assertEquals(refund, mutationDao.rows.getValue(refund.id),
                "the original refund key, body and CNY-root OCC must survive correction completion")
        } finally {
            release.complete(Unit)
            attempt.cancelAndJoin()
        }
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
    fun directRefundPublishesAuthoritativeBundleAndPreservesRootDate() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(
            cachedConfirmedEntity(9, "root-9", "高德").copy(
                rowVersion = 3,
                streamDate = "2026-05-07",
                streamAmountCents = 1_200,
                lineageStatus = "confirmed",
                lineageHomeNetCents = 1_200,
            ),
        )
        val api = OffsetApiService(
            FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            createResponse = expenseFactBundleDtoFixture(
                root = confirmedExpenseDtoFixture(
                    ConfirmedExpenseFixture(amountCents = 1_200, rowVersion = 4),
                ),
            ),
        )
        val repository = buildRepository(api, dao)

        val outcome = repository.createExpenseOffsetAllowingOffline(
            requireNotNull(repository.observeCorrections().first().access).binding,
            rootExpense(rowVersion = 3),
            ExpenseOffsetDraft(StreamOffsetKind.Refund, 300, "2026-09-03", " 退款到账 "),
        ).getOrThrow()

        val synced = assertIs<ExpenseOffsetMutationOutcome.Synced>(outcome)
        assertTrue(!synced.refreshPending)
        assertEquals(3L, api.createRequest?.expectedRowVersion)
        assertNotNull(api.idempotencyKey)
        val cachedRoot = assertNotNull(dao.findByServerId("owner", 9))
        assertEquals("2026-05-07", cachedRoot.streamDate)
        assertEquals(1_200L, cachedRoot.streamAmountCents)
        assertEquals("refund-1", dao.getConfirmedStreamOffsets("owner").single().publicId)
    }

    @Test
    fun networkLossQueuesRefundIntentWithoutCreatingPhantomStreamRow() = runTest {
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
        assertEquals(api.idempotencyKey, row.idempotencyKey)
        val originalRequest = moshi().adapter(ExpenseOffsetCreateRequestDto::class.java).fromJson(row.payload)
        assertEquals(api.createRequest, originalRequest)
        assertEquals(7L, originalRequest?.expectedRowVersion)
    }

    @Test
    fun voidUsesOffsetOccAndRemovesOnlyTheServerOmittedActiveOffset() = runTest {
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
        val repository = buildRepository(api, dao)

        val outcome = repository.voidExpenseOffsetAllowingOffline(
            rootExpense(rowVersion = 3),
            offsetFact(rowVersion = 2),
            "误记退款",
        ).getOrThrow()

        assertIs<ExpenseOffsetMutationOutcome.Synced>(outcome)
        assertEquals(2L, api.voidRequest?.expectedRowVersion)
        assertTrue(dao.getConfirmedStreamOffsets("owner").isEmpty())
    }

    @Test
    fun networkLossQueuesVoidBehindTheSameRootAndCarriesItsOffsetIdentity() = runTest {
        val mutationDao = FakePendingMutationDao()
        val repository = buildRepository(
            api = OffsetApiService(
                FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
                failure = IOException("offline"),
            ),
            dao = FakeExpenseDao(),
            outbox = testOutboxRepository(dao = mutationDao),
        )

        val outcome = repository.voidExpenseOffsetAllowingOffline(
            rootExpense(rowVersion = 7),
            offsetFact(rowVersion = 2),
            "误记退款",
        ).getOrThrow()

        assertIs<ExpenseOffsetMutationOutcome.Queued>(outcome)
        val row = mutationDao.rows.values.single()
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
            offsetCreateAdapter = moshi().adapter(ExpenseOffsetCreateRequestDto::class.java).takeIf { outbox != null },
            offsetVoidAdapter = moshi().adapter(ExpenseOffsetVoidOutboxPayload::class.java).takeIf { outbox != null },
            correctionAdapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            billSplitReceiptAdapter = com.ticketbox.OutboxAdapterGraph().billSplitReceiptAdapter,
            billSplitCreateAdapter = com.ticketbox.OutboxAdapterGraph().billSplitCreateAdapter,
            legacyCorrectionAdapter = com.ticketbox.OutboxAdapterGraph().legacyCorrectionAdapter,
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
