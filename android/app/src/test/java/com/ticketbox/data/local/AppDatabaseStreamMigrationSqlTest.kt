package com.ticketbox.data.local

import org.junit.Test
import java.sql.Connection
import java.sql.DriverManager
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AppDatabaseStreamMigrationSqlTest {
    @Test
    fun migration16To17AddsServerOwnedStreamProjection() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(V16_EXPENSES_SQL)
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, " +
                        "originalCurrencyCode, fxStatus, category, source, duplicateStatus, status, " +
                        "createdAt, rowVersion) VALUES ('owner', 9, 'root-9', 'CNY', 'CNY', " +
                        "'ready', '餐饮', '缓存', 'none', 'confirmed', '2026-05-13T00:00:00Z', 7)",
                )
                AppDatabase.MIGRATION_16_17_STATEMENTS.forEach(st::execute)
                st.execute(
                    "INSERT INTO expense_offset_stream (ledgerId, publicId, rootServerId, kind, " +
                        "streamDate, streamSortTime, streamSortId, streamAmountCents, amountCents, originalAmountMinor, " +
                        "originalCurrencyCode, homeCurrencyCode, category) VALUES " +
                        "('owner', 'refund-1', 9, 'refund', '2026-09-03', " +
                        "'2026-09-03T04:00:00Z', 22, -300, 300, 300, " +
                        "'CNY', 'CNY', '餐饮')",
                )
            }

            val columns = conn.columns("expenses")
            assertTrue(columns.contains("streamDate"))
            assertTrue(columns.contains("streamSortTime"))
            assertTrue(columns.contains("streamSortId"))
            assertTrue(columns.contains("streamAmountCents"))
            assertTrue(columns.contains("lineageStatus"))
            assertTrue(columns.contains("lineageHomeNetCents"))
            conn.query("SELECT rowVersion, streamDate FROM expenses WHERE serverId = 9") { rs ->
                assertTrue(rs.next(), "the cached root must survive")
                assertEquals(7L, rs.getLong(1))
                rs.getString(2)
                assertTrue(rs.wasNull(), "old rows wait for a server stream projection")
            }
            conn.query(
                "SELECT rootServerId, streamSortTime, streamSortId, streamAmountCents " +
                    "FROM expense_offset_stream",
            ) { rs ->
                assertTrue(rs.next())
                assertEquals(9L, rs.getLong(1))
                assertEquals("2026-09-03T04:00:00Z", rs.getString(2))
                assertEquals(22L, rs.getLong(3))
                assertEquals(-300L, rs.getLong(4))
            }
        }
    }

    private fun Connection.columns(table: String): Set<String> = buildSet {
        query("PRAGMA table_info($table)") { rs ->
            while (rs.next()) add(rs.getString("name"))
        }
    }

    private inline fun <T> Connection.query(sql: String, block: (java.sql.ResultSet) -> T): T =
        createStatement().use { statement -> statement.executeQuery(sql).use(block) }
}
