package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class UndatedConfirmedStreamTest {
    @Test
    fun nullDateFromWireIsRetainedWithoutSyntheticDay() {
        val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
            .adapter(ConfirmedExpenseStreamItemDto::class.java)
        val dated = envelope()
        val json = adapter.toJson(dated).replace("\"stream_date\":\"2026-09-03\"", "\"stream_date\":null")
        val parsed = requireNotNull(adapter.fromJson(json))
        assertNull(parsed.streamDate)
        assertNull(parsed.toConfirmedStreamCacheItem("owner").root.streamDate)
    }

    @Test
    fun completeUndatedProjectionSurvivesCacheAndOldReceiptWithoutRevivingOldDate() = runTest {
        val dao = FakeExpenseDao()
        val dated = envelope().toConfirmedStreamCacheItem("owner").root
        dao.upsertByServerIdForLedger("owner", dated)
        val unknown = dated.copy(streamDate = null, timePrecision = "unknown", accountingDate = null)
        dao.upsertByServerIdForLedger("owner", unknown)
        val stored = dao.getConfirmed("owner").single()
        assertNull(stored.streamDate)
        assertEquals(1, confirmedStreamFromCache(listOf(stored), emptyList()).size)
        val oldReceipt = envelope().root.toEntity("owner")
        dao.upsertByServerIdForLedger("owner", oldReceipt)
        val replayed = dao.getConfirmed("owner").single()
        assertNull(replayed.streamDate)
        assertEquals("unknown", replayed.timePrecision)
        assertEquals(1, confirmedStreamFromCache(listOf(replayed), emptyList()).size)
        assertEquals(0, confirmedStreamFromCache(listOf(oldReceipt), emptyList()).size)
    }
}

private fun envelope() = ConfirmedExpenseStreamItemDto(
    entryKind = ConfirmedStreamEntryKindDto.Expense,
    streamDate = "2026-09-03",
    streamSortTime = "2026-09-03T04:00:00Z",
    streamSortId = 9,
    streamAmountCents = 1200,
    root = confirmedExpenseDtoFixture(ConfirmedExpenseFixture()).copy(expenseTime = null, confirmedAt = null),
    offset = null,
    lineageStatus = ExpenseLineageStatusDto.Confirmed,
    lineageHomeNetCents = 1200,
)
