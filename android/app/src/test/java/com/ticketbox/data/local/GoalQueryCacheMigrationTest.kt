package com.ticketbox.data.local

import java.sql.DriverManager
import kotlin.test.Test
import kotlin.test.assertEquals

class GoalQueryCacheMigrationTest {
    @Test fun addingGoalReadsKeepsExpenseStatsAndOriginalOutboxBytes() {
        DriverManager.getConnection("jdbc:sqlite::memory:").use { db ->
            db.createStatement().use { sql ->
                sql.execute("CREATE TABLE expenses (id INTEGER PRIMARY KEY, amountCents INTEGER)")
                sql.execute("INSERT INTO expenses VALUES (1, 12)")
                sql.execute("CREATE TABLE pending_mutations (id INTEGER PRIMARY KEY, payload TEXT, idempotencyKey TEXT, expectedRowVersion INTEGER)")
                sql.execute("INSERT INTO pending_mutations VALUES (7, 'original-bytes', 'original-key', 3)")
                AppDatabase.MIGRATION_18_19_STATEMENTS.forEach(sql::execute)
                sql.execute("INSERT INTO stats_projection_cache VALUES ('binding', 'ledger', 'monthly', '2026-09', '', 'JPY', 'Asia/Tokyo', 'original-stats', 'original-time')")
                AppDatabase.MIGRATION_19_20_STATEMENTS.forEach(sql::execute)
                sql.executeQuery("SELECT amountCents FROM expenses").use { it.next(); assertEquals(12, it.getInt(1)) }
                sql.executeQuery("SELECT payload, idempotencyKey, expectedRowVersion FROM pending_mutations").use {
                    it.next(); assertEquals("original-bytes", it.getString(1)); assertEquals("original-key", it.getString(2)); assertEquals(3, it.getInt(3))
                }
                sql.executeQuery("SELECT count(*) FROM goal_query_cache").use { it.next(); assertEquals(0, it.getInt(1)) }
                sql.executeQuery("SELECT responseJson, fetchedAt FROM stats_projection_cache").use {
                    it.next(); assertEquals("original-stats", it.getString(1)); assertEquals("original-time", it.getString(2))
                }
            }
        }
    }
}
