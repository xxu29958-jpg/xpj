package com.ticketbox.data.local

import java.sql.DriverManager
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class AccountingTimeMigrationTest {
    @Test fun calendarCacheExpansionPreservesOldFactAndFrozenCommand() {
        DriverManager.getConnection("jdbc:sqlite::memory:").use { db ->
            db.createStatement().use { sql ->
                sql.execute("CREATE TABLE expenses (id INTEGER PRIMARY KEY, expenseTime TEXT, rowVersion INTEGER)")
                sql.execute("INSERT INTO expenses VALUES (1, '2026-04-30T16:30:00Z', 7)")
                sql.execute("CREATE TABLE pending_mutations (payload TEXT, idempotencyKey TEXT, receiptJson TEXT)")
                sql.execute("INSERT INTO pending_mutations VALUES ('original-json', 'original-key', 'original-receipt')")
                AppDatabase.MIGRATION_20_21_STATEMENTS.forEach(sql::execute)
                sql.executeQuery("SELECT expenseTime, rowVersion, timePrecision, accountingDate, calendarRevision FROM expenses").use {
                    it.next()
                    assertEquals("2026-04-30T16:30:00Z", it.getString(1))
                    assertEquals(7, it.getInt(2))
                    assertNull(it.getString(3))
                    assertNull(it.getString(4))
                    assertNull(it.getObject(5))
                }
                sql.executeQuery("SELECT payload, idempotencyKey, receiptJson FROM pending_mutations").use {
                    it.next()
                    assertEquals("original-json", it.getString(1))
                    assertEquals("original-key", it.getString(2))
                    assertEquals("original-receipt", it.getString(3))
                }
            }
        }
    }
}
