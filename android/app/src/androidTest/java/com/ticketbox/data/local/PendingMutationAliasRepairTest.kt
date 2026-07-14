package com.ticketbox.data.local

import android.content.Context
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.repository.OutboxBinding
import com.ticketbox.data.repository.OutboxRepository
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PendingMutationAliasRepairTest {
    private val context: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val databaseName = "pending-mutation-alias-repair.db"
    private var database: AppDatabase? = null

    @After
    fun cleanDatabase() {
        database?.close()
        database = null
        context.deleteDatabase(databaseName)
    }

    @Test
    fun roomAliasRepairIsIdempotentAfterStaleSettingsRestart() = runBlocking {
        val firstDatabase = reopenDatabase()
        firstDatabase.pendingMutationDao().insert(aliasBoundMutation())

        val firstProcess = repositoryWithStaleSettings(firstDatabase)
        assertEquals("expense:7", firstProcess.dequeueNextRunnable().single().targetId)
        assertSingleCanonicalRow(firstDatabase)

        val restartedDatabase = reopenDatabase()
        val restartedProcess = repositoryWithStaleSettings(restartedDatabase)
        restartedProcess.adoptLegacyRowsForCurrentBinding()
        restartedProcess.adoptLegacyRowsForCurrentBinding()

        assertSingleCanonicalRow(restartedDatabase)
        assertEquals("expense:7", restartedProcess.dequeueNextRunnable().single().targetId)
    }

    private fun reopenDatabase(): AppDatabase {
        database?.close()
        return Room.databaseBuilder(context, AppDatabase::class.java, databaseName)
            .build()
            .also { database = it }
    }

    private fun repositoryWithStaleSettings(database: AppDatabase): OutboxRepository =
        OutboxRepository(
            dao = database.pendingMutationDao(),
            bindingProvider = {
                OutboxBinding(
                    serverUrl = "https://API.EXAMPLE.COM:443",
                    ledgerId = "owner",
                )
            },
        )

    private fun aliasBoundMutation(): PendingMutationEntity = PendingMutationEntity(
        serverUrl = "https://API.EXAMPLE.COM:443",
        ledgerId = "owner",
        type = PendingMutationType.PatchExpense.wireValue,
        targetId = "expense:7",
        payload = "{}",
        expectedRowVersion = 1,
        status = PendingMutationStatus.Pending.wireValue,
        createdAt = "2026-07-14T00:00:00.000Z",
    )

    private fun assertSingleCanonicalRow(database: AppDatabase) {
        database.openHelper.readableDatabase.query(
            "SELECT serverUrl, COUNT(*) FROM pending_mutations GROUP BY serverUrl",
        ).use { cursor ->
            assertTrue(cursor.moveToFirst())
            assertEquals("https://api.example.com", cursor.getString(0))
            assertEquals(1L, cursor.getLong(1))
            assertTrue(cursor.isLast)
        }
    }
}
