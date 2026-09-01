package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.ExpenseOffsetStatus
import com.ticketbox.domain.model.StreamOffsetKind
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

internal class ExpenseOffsetRepositoryTest : ExpensePendingRepositoryOutboxTestBase() {
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
        assertTrue(row.payload.contains("\"expected_row_version\":0"), row.payload)
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
            outbox = outbox,
            offsetCreateAdapter = moshi().adapter(ExpenseOffsetCreateRequestDto::class.java),
            offsetVoidAdapter = moshi().adapter(ExpenseOffsetVoidOutboxPayload::class.java),
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
