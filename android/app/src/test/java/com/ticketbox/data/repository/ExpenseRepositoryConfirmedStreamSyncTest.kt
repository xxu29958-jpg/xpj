package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import com.ticketbox.data.remote.dto.ConfirmedOffsetStreamDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ExpenseRepositoryConfirmedStreamSyncTest {
    @Test
    fun typedStreamSyncCachesRootProjectionAndOffsetEvent() = runTest {
        val dao = FakeExpenseDao()
        val root = confirmedExpenseDtoFixture(
            ConfirmedExpenseFixture(
                amountCents = 1_200,
                expenseTime = "2026-08-15T04:00:00Z",
            ),
        )
        val partialLineage = ConfirmedLineageFixture(
            status = ExpenseLineageStatusDto.PartiallyRefunded,
            homeNetCents = 900,
        )
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).apply {
            confirmedResponses[1] = PaginatedExpensesDto(
                items = listOf(
                    confirmedStreamEnvelopeFixture(
                        ConfirmedStreamFixture(
                            streamDate = "2026-08-15",
                            streamAmountCents = 1_200,
                            root = root,
                            lineage = partialLineage,
                        ),
                    ),
                    confirmedStreamEnvelopeFixture(
                        ConfirmedStreamFixture(
                            entryKind = ConfirmedStreamEntryKindDto.Offset,
                            streamDate = "2026-09-03",
                            streamAmountCents = -300,
                            root = root,
                            offset = refundOffsetFixture(),
                            lineage = partialLineage,
                        ),
                    ),
                ),
                page = 1,
                pageSize = 200,
                total = 2,
            )
        }

        confirmedRepository(dao, apiService).syncConfirmed().getOrThrow()

        val cachedRoot = dao.findByServerId("owner", root.id)!!
        assertEquals("2026-08-15", cachedRoot.streamDate)
        assertEquals(1_200L, cachedRoot.streamAmountCents)
        assertEquals("partially_refunded", cachedRoot.lineageStatus)
        val cachedOffset = dao.getConfirmedStreamOffsets("owner").single()
        assertEquals("refund-1", cachedOffset.publicId)
        assertEquals("2026-09-03", cachedOffset.streamDate)
        assertEquals(-300L, cachedOffset.streamAmountCents)
    }

    @Test
    fun malformedTypedStreamFailsBeforeAnyCacheWrite() = runTest {
        val dao = FakeExpenseDao()
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).apply {
            confirmedResponses[1] = PaginatedExpensesDto(
                items = listOf(
                    confirmedStreamEnvelopeFixture(
                        ConfirmedStreamFixture(offset = refundOffsetFixture()),
                    ),
                ),
                page = 1,
                pageSize = 200,
                total = 1,
            )
        }

        val failure = confirmedRepository(dao, apiService).syncConfirmed().exceptionOrNull()

        assertTrue(failure is RepositoryException)
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmedStreamOffsets("owner").isEmpty())
    }

    @Test
    fun filteredSyncPrunesOnlyMissingOffsetsInsideItsServerScope() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(9, "root-9", "高德").copy(tags = "AI"))
        dao.upsertConfirmedStreamOffsets(
            listOf(
                cachedOffset("refund-in-scope", streamDate = "2026-05-10", category = "交通"),
                cachedOffset("refund-other-month", streamDate = "2026-06-10", category = "交通"),
            ),
        )
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)

        confirmedRepository(dao, apiService)
            .syncConfirmed(month = "2026-05", category = "交通", tag = "AI")
            .getOrThrow()

        assertEquals(
            listOf("refund-other-month"),
            dao.getConfirmedStreamOffsets("owner").map { it.publicId },
        )
    }
}

private fun confirmedRepository(
    dao: FakeExpenseDao,
    apiService: FakeApiService,
): ExpenseRepository = ExpenseRepository(
    expenseDao = dao,
    binding = testServerSessionBinding(
        apiClient = FakeApiServiceFactory(apiService),
        settingsStore = boundSettingsStore(),
        tokenStore = TestSessionFixture().apply { saveToken("session-token") },
    ),
    deviceNameProvider = { "Android Test Device" },
)

private fun refundOffsetFixture(): ConfirmedOffsetStreamDto = ConfirmedOffsetStreamDto(
    publicId = "refund-1",
    kind = ExpenseOffsetKindDto.Refund,
    amountCents = 300,
    originalAmountMinor = 300,
    originalCurrencyCode = "CNY",
    homeCurrencyCode = "CNY",
    category = "交通",
)

private fun cachedOffset(
    publicId: String,
    streamDate: String,
    category: String,
): ExpenseOffsetStreamEntity = ExpenseOffsetStreamEntity(
    ledgerId = "owner",
    publicId = publicId,
    rootServerId = 9,
    kind = "refund",
    streamDate = streamDate,
    streamSortTime = "2026-09-03T04:00:00Z",
    streamSortId = 22,
    streamAmountCents = -300,
    amountCents = 300,
    originalAmountMinor = 300,
    originalCurrencyCode = "CNY",
    homeCurrencyCode = "CNY",
    category = category,
)
