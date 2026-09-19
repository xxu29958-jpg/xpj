package com.ticketbox.data.repository

import android.app.Application
import com.ticketbox.ui.resolve
import androidx.room.Room
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.ui.components.expenseTimeLabel
import com.ticketbox.ui.screens.groupConfirmedStream
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.assertEquals
import kotlin.test.assertNull

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class UndatedRoomProjectionTest {
    @Test
    fun roomDistinguishesAnUndatedRootFromAnAbsentStreamProjection() = runBlocking {
        val context = RuntimeEnvironment.getApplication()
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).allowMainThreadQueries().build()
        try {
            val dao = db.expenseDao()
            val raw = confirmedExpenseDtoFixture().copy(expenseTime = null, confirmedAt = null).toEntity("owner")
            val unknown = raw.copy(streamDate = null, streamSortTime = "2026-09-03T04:00:00Z", streamSortId = 9,
                streamAmountCents = 1200, lineageStatus = "confirmed", lineageHomeNetCents = 1200, timePrecision = "unknown")
            dao.upsertByServerIdForLedger("owner", unknown)
            dao.upsertByServerIdForLedger("owner", raw.copy(serverId = 10, publicId = "absent-projection"))
            assertEquals(listOf(9L), dao.observeConfirmedStreamRoots("owner").first().map { it.serverId })
            dao.upsertByServerIdForLedger("owner", raw)
            val rows = dao.observeConfirmedStreamRoots("owner").first()
            val stream = confirmedStreamFromCache(rows, emptyList())
            assertEquals(1, stream.size)
            assertNull(stream.single().streamDate)
            assertEquals("账务日期待核对", expenseTimeLabel(stream.single().root).resolve(context))
            val group = groupConfirmedStream(context.resources, stream).single()
            assertEquals("账务日期待核对", group.label)
            assertEquals(mapOf<String?, Long?>("CNY" to 1200L), group.amountsByCurrency)
        } finally { db.close() }
    }
}
