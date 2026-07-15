package com.ticketbox.data.local

import android.content.Context
import android.database.Cursor
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.repository.OutboxBinding
import com.ticketbox.data.repository.OutboxOwnerIdentity
import com.ticketbox.data.repository.OutboxRepository
import kotlinx.coroutines.flow.first
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
        firstDatabase.pendingMutationDao().insert(canonicalMutation())
        firstDatabase.pendingMutationDao().insert(otherOriginMutation())
        firstDatabase.pendingMutationDao().insert(unownedLegacyMutation())
        val otherOriginBefore = rowFingerprint(firstDatabase, "expense:other-origin")
        val unownedBefore = rowFingerprint(firstDatabase, "expense:legacy-unowned")

        val firstProcess = repositoryWithStaleSettings(firstDatabase)
        assertEquals(2, firstProcess.dequeueNextRunnable().size)
        assertEquals(2, firstProcess.observeStatus().first().quarantinedCount)
        assertExpectedOrigins(firstDatabase)
        assertEquals(otherOriginBefore, rowFingerprint(firstDatabase, "expense:other-origin"))
        assertEquals(unownedBefore, rowFingerprint(firstDatabase, "expense:legacy-unowned"))

        val restartedDatabase = reopenDatabase()
        val restartedProcess = repositoryWithStaleSettings(restartedDatabase)
        restartedProcess.dequeueNextRunnable()
        restartedProcess.dequeueNextRunnable()

        assertExpectedOrigins(restartedDatabase)
        assertEquals(otherOriginBefore, rowFingerprint(restartedDatabase, "expense:other-origin"))
        assertEquals(unownedBefore, rowFingerprint(restartedDatabase, "expense:legacy-unowned"))
        assertEquals(2, restartedProcess.observeStatus().first().quarantinedCount)
        assertEquals(2, restartedProcess.dequeueNextRunnable().size)
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
                    owner = OWNER,
                )
            },
        )

    private fun aliasBoundMutation(): PendingMutationEntity = PendingMutationEntity(
        serverUrl = "https://API.EXAMPLE.COM:443",
        ledgerId = "owner",
        ownerKey = OWNER.storageKey,
        type = PendingMutationType.PatchExpense.wireValue,
        targetId = "expense:7",
        payload = "{}",
        expectedRowVersion = 1,
        status = PendingMutationStatus.Pending.wireValue,
        createdAt = "2026-07-14T00:00:00.000Z",
    )

    private fun canonicalMutation(): PendingMutationEntity = aliasBoundMutation().copy(
        serverUrl = "https://api.example.com",
        targetId = "expense:canonical",
        createdAt = "2026-07-14T00:00:01.000Z",
    )

    private fun otherOriginMutation(): PendingMutationEntity = aliasBoundMutation().copy(
        serverUrl = "https://other.example.com",
        ownerKey = OTHER_OWNER.storageKey,
        targetId = "expense:other-origin",
        payload = "{\"origin\":\"other\"}",
        expectedRowVersion = 9,
        createdAt = "2026-07-14T00:00:02.000Z",
    )

    private fun unownedLegacyMutation(): PendingMutationEntity = aliasBoundMutation().copy(
        serverUrl = "https://legacy.example.com",
        ownerKey = null,
        targetId = "expense:legacy-unowned",
        createdAt = "2026-07-14T00:00:03.000Z",
    )

    private fun assertExpectedOrigins(database: AppDatabase) {
        database.openHelper.readableDatabase.query(
            "SELECT serverUrl, COUNT(*) FROM pending_mutations GROUP BY serverUrl ORDER BY serverUrl",
        ).use { cursor ->
            assertTrue(cursor.moveToFirst())
            assertEquals("https://api.example.com", cursor.getString(0))
            assertEquals(2L, cursor.getLong(1))
            assertTrue(cursor.moveToNext())
            assertEquals("https://legacy.example.com", cursor.getString(0))
            assertEquals(1L, cursor.getLong(1))
            assertTrue(cursor.moveToNext())
            assertEquals("https://other.example.com", cursor.getString(0))
            assertEquals(1L, cursor.getLong(1))
            assertTrue(cursor.isLast)
        }
    }

    private fun rowFingerprint(database: AppDatabase, targetId: String): List<Pair<String, String?>> {
        database.openHelper.readableDatabase.query(
            "SELECT * FROM pending_mutations WHERE targetId = ?",
            arrayOf(targetId),
        ).use { cursor ->
            assertTrue(cursor.moveToFirst())
            assertTrue(cursor.isLast)
            return cursor.columnNames.mapIndexed { index, name ->
                name to cursor.valueAt(index)
            }
        }
    }

    private fun Cursor.valueAt(index: Int): String? = when (getType(index)) {
        Cursor.FIELD_TYPE_NULL -> null
        Cursor.FIELD_TYPE_BLOB -> getBlob(index).joinToString(separator = ",")
        else -> getString(index)
    }

    companion object {
        private val OWNER = requireNotNull(
            OutboxOwnerIdentity.fromOrNull(
                serverId = "20000000-0000-0000-0000-000000000001",
                dataGeneration = "20000000-0000-0000-0000-000000000002",
                accountPublicId = "20000000-0000-0000-0000-000000000003",
                devicePublicId = "20000000-0000-0000-0000-000000000004",
            ),
        )
        private val OTHER_OWNER = requireNotNull(
            OutboxOwnerIdentity.fromOrNull(
                serverId = "30000000-0000-0000-0000-000000000001",
                dataGeneration = "30000000-0000-0000-0000-000000000002",
                accountPublicId = "30000000-0000-0000-0000-000000000003",
                devicePublicId = "30000000-0000-0000-0000-000000000004",
            ),
        )
    }
}
