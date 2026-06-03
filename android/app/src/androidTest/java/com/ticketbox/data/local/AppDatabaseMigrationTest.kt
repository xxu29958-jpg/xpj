package com.ticketbox.data.local

import androidx.room.testing.MigrationTestHelper
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * ADR-0041 P2 (review): the v10→v11 migration is install-upgrade-critical —
 * it adds ``expenses.rowVersion`` (DEFAULT 1) and DROPs + rebuilds
 * ``pending_mutations`` with the new INTEGER ``expectedRowVersion`` column and
 * its 6 indices. Static schema alignment with 11.json was verified by hand,
 * but only a real [MigrationTestHelper] run exercises the actual migration SQL
 * against SQLite and validates the resulting schema against the exported
 * 11.json — catching upgrade crashes and schema/index drift the fake-DAO unit
 * suite (which never opens Room) cannot.
 */
class AppDatabaseMigrationTest {
    private val dbName = "migration-10-11-test.db"

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        AppDatabase::class.java,
    )

    @Test
    fun migrate10To11BackfillsRowVersionAndRebuildsOutbox() {
        // Seed a v10 expenses row (the rowVersion column did not exist yet) and
        // a v10 pending_mutations row (string-token era).
        helper.createDatabase(dbName, 10).use { db ->
            db.execSQL(
                """
                INSERT INTO expenses (
                    id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, merchant, category, source,
                    duplicateStatus, status, createdAt
                ) VALUES (
                    1, 'owner', 9, 'pub-9', 1500, 'CNY',
                    'CNY', 'ready', '星巴克', '餐饮', '缓存',
                    'none', 'confirmed', '2026-05-13T00:00:00Z'
                )
                """.trimIndent(),
            )
            db.execSQL(
                """
                INSERT INTO pending_mutations (
                    serverUrl, ledgerId, type, targetId, payload, expectedUpdatedAt,
                    status, retryCount, createdAt
                ) VALUES (
                    'https://api.example.com', 'owner', 'patch_expense', 'expense:9',
                    '{}', '2026-05-13T00:00:00Z', 'pending', 0, '2026-05-13T00:00:00Z'
                )
                """.trimIndent(),
            )
        }

        // Applies Migration10To11 and asserts the resulting schema matches
        // 11.json exactly (validateDroppedTables = true).
        val db = helper.runMigrationsAndValidate(
            dbName,
            11,
            true,
            AppDatabase.Migration10To11,
        )

        // The pre-existing cached row survives and gains rowVersion via DEFAULT 1.
        db.query("SELECT rowVersion FROM expenses WHERE serverId = 9").use { cursor ->
            assertTrue("migrated expenses row must survive", cursor.moveToFirst())
            assertEquals(1L, cursor.getLong(0))
        }
        // pending_mutations was dropped + recreated empty (string tokens can't
        // replay against the int-CAS backend — intentional outbox reset).
        db.query("SELECT COUNT(*) FROM pending_mutations").use { cursor ->
            assertTrue(cursor.moveToFirst())
            assertEquals("v10→v11 intentionally clears the outbox", 0L, cursor.getLong(0))
        }
    }
}
