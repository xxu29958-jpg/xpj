package com.ticketbox.data.local

import org.junit.Test
import java.sql.Connection
import java.sql.DriverManager
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * JVM unit test for the Room v10→v11 migration. It seeds the v10 schema into an
 * in-memory SQLite (sqlite-jdbc), runs the EXACT production statements
 * ([AppDatabase.MIGRATION_10_11_STATEMENTS]), then introspects the result.
 *
 * This is the fast, emulator-free floor; the instrumented [AppDatabaseMigrationTest]
 * additionally validates the migrated schema against Room's exported 11.json on a
 * device. Running the real migration SQL against real SQLite here catches the two
 * failure modes that matter on a device upgrade — (1) a statement SQLite rejects
 * (crash) and (2) schema drift: the rowVersion backfill, the TEXT→INTEGER
 * token-column flip, and the rebuilt index set — locally, on every JVM test run.
 */
class AppDatabaseMigrationSqlTest {

    // v10 schema (from schemas/com.ticketbox.data.local.AppDatabase/10.json
    // createSql, with `${'$'}{TABLE_NAME}` resolved to the real table names).
    private val v10Expenses =
        "CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, ledgerId TEXT NOT NULL, " +
            "serverId INTEGER NOT NULL, publicId TEXT NOT NULL, amountCents INTEGER, homeCurrencyCode TEXT NOT NULL, " +
            "originalCurrencyCode TEXT NOT NULL, originalAmountMinor INTEGER, exchangeRateToCny TEXT, " +
            "exchangeRateDate TEXT, exchangeRateSource TEXT, fxStatus TEXT NOT NULL, merchant TEXT, " +
            "category TEXT NOT NULL, note TEXT, source TEXT NOT NULL, thumbnailPath TEXT, imageDeletedAt TEXT, " +
            "thumbnailDeletedAt TEXT, imageHash TEXT, rawText TEXT, confidence REAL, duplicateStatus TEXT NOT NULL, " +
            "duplicateOfId INTEGER, duplicateReason TEXT, tags TEXT, valueScore INTEGER, regretScore INTEGER, " +
            "status TEXT NOT NULL, expenseTime TEXT, createdAt TEXT NOT NULL, confirmedAt TEXT, updatedAt TEXT)"

    private val v10PendingMutations =
        "CREATE TABLE pending_mutations (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
            "serverUrl TEXT NOT NULL DEFAULT '', ledgerId TEXT NOT NULL DEFAULT '', type TEXT NOT NULL, " +
            "targetId TEXT NOT NULL, payload TEXT NOT NULL, expectedUpdatedAt TEXT NOT NULL, status TEXT NOT NULL, " +
            "retryCount INTEGER NOT NULL DEFAULT 0, lastError TEXT, createdAt TEXT NOT NULL, attemptedAt TEXT, " +
            "completedAt TEXT)"

    @Test
    fun migration10To11RunsAgainstSqliteAndProducesExpectedSchema() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(v10Expenses)
                st.execute(v10PendingMutations)
                // Seed a v10 expenses row (rowVersion column doesn't exist yet) and a
                // v10 string-token outbox row.
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, duplicateStatus, status, createdAt) VALUES " +
                        "('owner', 9, 'pub-9', 'CNY', 'CNY', 'ready', '餐饮', '缓存', 'none', 'confirmed', '2026-05-13T00:00:00Z')",
                )
                st.execute(
                    "INSERT INTO pending_mutations (serverUrl, ledgerId, type, targetId, payload, expectedUpdatedAt, " +
                        "status, createdAt) VALUES ('s', 'owner', 'patch_expense', 'expense:9', '{}', " +
                        "'2026-05-13T00:00:00Z', 'pending', '2026-05-13T00:00:00Z')",
                )

                // Run the EXACT production migration statements, in order.
                AppDatabase.MIGRATION_10_11_STATEMENTS.forEach { st.execute(it) }
            }

            // expenses gains rowVersion; the preserved v10 row backfills to DEFAULT 1.
            assertTrue(conn.columns("expenses").contains("rowVersion"), "expenses must gain a rowVersion column")
            conn.query("SELECT rowVersion FROM expenses WHERE serverId = 9") { rs ->
                assertTrue(rs.next(), "the pre-existing expenses row must survive the migration")
                assertEquals(1L, rs.getLong(1), "migrated rows default to rowVersion 1")
            }

            // pending_mutations: token column flipped TEXT→INTEGER, table rebuilt empty.
            val outboxCols = conn.columns("pending_mutations")
            assertTrue(outboxCols.contains("expectedRowVersion"), "outbox token column must be expectedRowVersion")
            assertFalse(outboxCols.contains("expectedUpdatedAt"), "old expectedUpdatedAt column must be gone")
            conn.query("SELECT COUNT(*) FROM pending_mutations") { rs ->
                rs.next()
                assertEquals(0, rs.getInt(1), "v10→v11 intentionally drops + rebuilds the outbox empty")
            }
            // All 6 outbox indices recreated.
            conn.query(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND tbl_name = 'pending_mutations' " +
                    "AND name LIKE 'index_%'",
            ) { rs ->
                rs.next()
                assertEquals(6, rs.getInt(1), "all 6 pending_mutations indices must be rebuilt")
            }
        }
    }

    private fun Connection.columns(table: String): Set<String> {
        val cols = mutableSetOf<String>()
        query("PRAGMA table_info($table)") { rs -> while (rs.next()) cols += rs.getString("name") }
        return cols
    }

    private inline fun <T> Connection.query(sql: String, block: (java.sql.ResultSet) -> T): T =
        createStatement().use { st -> st.executeQuery(sql).use(block) }
}
