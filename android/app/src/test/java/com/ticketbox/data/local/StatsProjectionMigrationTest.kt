package com.ticketbox.data.local

import java.sql.DriverManager
import kotlin.test.Test
import kotlin.test.assertEquals

class StatsProjectionMigrationTest {
    @Test
    fun addingReadSnapshotsPreservesExpenseFactsAndOriginalOutboxBytes() {
        DriverManager.getConnection("jdbc:sqlite::memory:").use { db ->
            db.createStatement().use { sql ->
                sql.execute("CREATE TABLE expenses (id INTEGER PRIMARY KEY, amountCents INTEGER, homeCurrencyCode TEXT)")
                sql.execute("INSERT INTO expenses VALUES (1, 1000, 'JPY')")
                sql.execute("CREATE TABLE pending_mutations (id INTEGER PRIMARY KEY, payload TEXT, idempotencyKey TEXT, expectedRowVersion INTEGER)")
                sql.execute("INSERT INTO pending_mutations VALUES (7, 'original-bytes', 'original-key', 3)")
                AppDatabase.MIGRATION_18_19_STATEMENTS.forEach(sql::execute)
                sql.executeQuery("SELECT amountCents, homeCurrencyCode FROM expenses").use {
                    it.next(); assertEquals(1000L, it.getLong(1)); assertEquals("JPY", it.getString(2))
                }
                sql.executeQuery("SELECT payload, idempotencyKey, expectedRowVersion FROM pending_mutations").use {
                    it.next(); assertEquals("original-bytes", it.getString(1)); assertEquals("original-key", it.getString(2)); assertEquals(3L, it.getLong(3))
                }
                sql.executeQuery("SELECT count(*) FROM stats_projection_cache").use { it.next(); assertEquals(0, it.getInt(1)) }
            }
        }
    }
}
