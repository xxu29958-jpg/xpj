package com.ticketbox.data.repository

import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedOffsetStreamDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class ConfirmedStreamCacheMapperTest {
    @Test
    fun offsetEnvelopeCachesItsCurrentRootAndServerProjection() {
        val item = confirmedStreamEnvelope(
            entryKind = ConfirmedStreamEntryKindDto.Offset,
            streamSortTime = "2026-09-03T04:00:00Z",
            streamSortId = 22,
            offset = offsetDto(),
        )

        val cached = item.toConfirmedStreamCacheItem("owner")

        assertEquals(9L, cached.root.serverId)
        assertNull(cached.root.streamDate)
        assertNull(cached.root.streamAmountCents)
        assertEquals("partially_refunded", cached.root.lineageStatus)
        assertEquals("refund-1", cached.offset?.publicId)
        assertEquals(9L, cached.offset?.rootServerId)
        assertEquals(-300L, cached.offset?.streamAmountCents)
        assertEquals("2026-09-03T04:00:00Z", cached.offset?.streamSortTime)
        assertEquals(22L, cached.offset?.streamSortId)
    }

    @Test
    fun cachedRowsRecoverTheServerOwnedGlobalOrderAcrossEntityTables() {
        val root = confirmedStreamEnvelope(
            entryKind = ConfirmedStreamEntryKindDto.Expense,
            streamSortTime = "2026-09-03T05:00:00Z",
            streamSortId = 9,
            offset = null,
        ).toConfirmedStreamCacheItem("owner").root
        val earlierOffset = confirmedStreamEnvelope(
            entryKind = ConfirmedStreamEntryKindDto.Offset,
            streamSortTime = "2026-09-03T04:00:00Z",
            streamSortId = 3,
            offset = offsetDto(),
        ).toConfirmedStreamCacheItem("owner").offset!!

        val rows = confirmedStreamFromCache(listOf(root), listOf(earlierOffset))

        assertEquals(listOf("expense-9", "offset-refund-1"), rows.map { it.rowKey })
    }

    @Test
    fun expenseEnvelopeOwnsTheRootStreamProjection() {
        val cached = confirmedStreamEnvelope(entryKind = ConfirmedStreamEntryKindDto.Expense, offset = null)
            .toConfirmedStreamCacheItem("owner")

        assertEquals("2026-09-03", cached.root.streamDate)
        assertEquals(-300L, cached.root.streamAmountCents)
        assertNull(cached.offset)
    }

    @Test
    fun malformedEnvelopeOrUnknownWireValueFailsClosed() {
        assertFailsWith<RepositoryException> {
            confirmedStreamEnvelope(entryKind = ConfirmedStreamEntryKindDto.Expense, offset = offsetDto())
                .toConfirmedStreamCacheItem("owner")
        }
        assertFailsWith<RepositoryException> {
            confirmedStreamEnvelope(
                entryKind = ConfirmedStreamEntryKindDto.Expense,
                streamSortTime = "not-a-time",
                offset = null,
            ).toConfirmedStreamCacheItem("owner")
        }
        val adapter = Moshi.Builder().build().adapter(ConfirmedStreamEntryKindDto::class.java)
        assertFailsWith<JsonDataException> {
            adapter.fromJson("\"future_kind\"")
        }
    }
}

private fun confirmedStreamEnvelope(
    entryKind: ConfirmedStreamEntryKindDto,
    streamSortTime: String = "2026-09-03T04:00:00Z",
    streamSortId: Long = 9,
    offset: ConfirmedOffsetStreamDto?,
): ConfirmedExpenseStreamItemDto = ConfirmedExpenseStreamItemDto(
    entryKind = entryKind,
    streamDate = "2026-09-03",
    streamSortTime = streamSortTime,
    streamSortId = streamSortId,
    streamAmountCents = -300,
    root = confirmedExpenseDtoFixture(
        ConfirmedExpenseFixture(
            amountCents = 1_200,
            merchant = "夏日酒店",
            category = "旅游",
            tags = "旅行",
            expenseTime = "2026-08-15T04:00:00Z",
            rowVersion = 2,
        ),
    ),
    offset = offset,
    lineageStatus = ExpenseLineageStatusDto.PartiallyRefunded,
    lineageHomeNetCents = 900,
)

private fun offsetDto() = ConfirmedOffsetStreamDto(
    publicId = "refund-1",
    kind = ExpenseOffsetKindDto.Refund,
    amountCents = 300,
    originalAmountMinor = 300,
    originalCurrencyCode = "CNY",
    homeCurrencyCode = "CNY",
    category = "餐饮",
)
