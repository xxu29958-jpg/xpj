package com.ticketbox.data.local

import org.junit.Test
import java.sql.Connection
import java.sql.DriverManager
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

internal const val V15_EXPENSES_SQL =
    "CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, ledgerId TEXT NOT NULL, " +
        "serverId INTEGER, publicId TEXT NOT NULL, amountCents INTEGER, homeCurrencyCode TEXT NOT NULL, " +
        "originalCurrencyCode TEXT NOT NULL, originalAmountMinor INTEGER, exchangeRateToCny TEXT, " +
        "exchangeRateDate TEXT, exchangeRateSource TEXT, fxStatus TEXT NOT NULL, merchant TEXT, " +
        "categoryRaw TEXT, category TEXT NOT NULL, note TEXT, source TEXT NOT NULL, " +
        "hasImage INTEGER NOT NULL DEFAULT 0, thumbnailPath TEXT, imageDeletedAt TEXT, " +
        "thumbnailDeletedAt TEXT, imageHash TEXT, rawText TEXT, confidence REAL, " +
        "duplicateStatus TEXT NOT NULL, duplicateOfId INTEGER, duplicateReason TEXT, tags TEXT, " +
        "valueScore INTEGER, regretScore INTEGER, status TEXT NOT NULL, expenseTime TEXT, " +
        "createdAt TEXT NOT NULL, confirmedAt TEXT, updatedAt TEXT, " +
        "rowVersion INTEGER NOT NULL DEFAULT 1, clientRef TEXT)"

internal val V16_EXPENSES_SQL = V15_EXPENSES_SQL
    .removeSuffix(")") + ", factRevision INTEGER NOT NULL DEFAULT 0)"

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

    // v11 schema: pending_mutations as rebuilt by MIGRATION_10_11 (int token).
    private val v11PendingMutations =
        "CREATE TABLE pending_mutations (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
            "serverUrl TEXT NOT NULL DEFAULT '', ledgerId TEXT NOT NULL DEFAULT '', type TEXT NOT NULL, " +
            "targetId TEXT NOT NULL, payload TEXT NOT NULL, expectedRowVersion INTEGER NOT NULL DEFAULT 0, " +
            "status TEXT NOT NULL, retryCount INTEGER NOT NULL DEFAULT 0, lastError TEXT, createdAt TEXT NOT NULL, " +
            "attemptedAt TEXT, completedAt TEXT)"

    // v12 expenses schema (from schemas/.../12.json createSql): serverId NOT NULL,
    // no clientRef column. Issue #65 slice 4's 12→13 makes serverId nullable and
    // adds clientRef + the (ledgerId, clientRef) unique index via a table rebuild.
    private val v12Expenses =
        "CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, ledgerId TEXT NOT NULL, " +
            "serverId INTEGER NOT NULL, publicId TEXT NOT NULL, amountCents INTEGER, homeCurrencyCode TEXT NOT NULL, " +
            "originalCurrencyCode TEXT NOT NULL, originalAmountMinor INTEGER, exchangeRateToCny TEXT, " +
            "exchangeRateDate TEXT, exchangeRateSource TEXT, fxStatus TEXT NOT NULL, merchant TEXT, " +
            "category TEXT NOT NULL, note TEXT, source TEXT NOT NULL, thumbnailPath TEXT, imageDeletedAt TEXT, " +
            "thumbnailDeletedAt TEXT, imageHash TEXT, rawText TEXT, confidence REAL, duplicateStatus TEXT NOT NULL, " +
            "duplicateOfId INTEGER, duplicateReason TEXT, tags TEXT, valueScore INTEGER, regretScore INTEGER, " +
            "status TEXT NOT NULL, expenseTime TEXT, createdAt TEXT NOT NULL, confirmedAt TEXT, updatedAt TEXT, " +
            "rowVersion INTEGER NOT NULL DEFAULT 1)"

    // v14 expenses schema (from schemas/.../14.json createSql): serverId nullable,
    // clientRef present, no categoryRaw / hasImage yet.
    private val v14Expenses =
        "CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, ledgerId TEXT NOT NULL, " +
            "serverId INTEGER, publicId TEXT NOT NULL, amountCents INTEGER, homeCurrencyCode TEXT NOT NULL, " +
            "originalCurrencyCode TEXT NOT NULL, originalAmountMinor INTEGER, exchangeRateToCny TEXT, " +
            "exchangeRateDate TEXT, exchangeRateSource TEXT, fxStatus TEXT NOT NULL, merchant TEXT, " +
            "category TEXT NOT NULL, note TEXT, source TEXT NOT NULL, thumbnailPath TEXT, imageDeletedAt TEXT, " +
            "thumbnailDeletedAt TEXT, imageHash TEXT, rawText TEXT, confidence REAL, duplicateStatus TEXT NOT NULL, " +
            "duplicateOfId INTEGER, duplicateReason TEXT, tags TEXT, valueScore INTEGER, regretScore INTEGER, " +
            "status TEXT NOT NULL, expenseTime TEXT, createdAt TEXT NOT NULL, confirmedAt TEXT, updatedAt TEXT, " +
            "rowVersion INTEGER NOT NULL DEFAULT 1, clientRef TEXT)"

    @Test
    fun migration15To16AddsFactRevisionAndPreservesRows() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(V15_EXPENSES_SQL)
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion) VALUES " +
                        "('owner', 9, 'pub-9', 'CNY', 'CNY', 'ready', '餐饮', '缓存', 'none', 'confirmed', " +
                        "'2026-05-13T00:00:00Z', 7)",
                )
                AppDatabase.MIGRATION_15_16_STATEMENTS.forEach(st::execute)
            }

            assertTrue(conn.columns("expenses").contains("factRevision"))
            conn.query("SELECT rowVersion, factRevision FROM expenses WHERE serverId = 9") { rs ->
                assertTrue(rs.next(), "the cached row must survive")
                assertEquals(7L, rs.getLong(1))
                assertEquals(0L, rs.getLong(2), "legacy cache rows self-heal from the server")
            }
        }
    }

    @Test
    fun migration14To15AddsQualityColumnsAndBackfillsHasImage() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(v14Expenses)
                // Live thumbnail ⇒ receipt image almost certainly present.
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, thumbnailPath, duplicateStatus, status, createdAt, rowVersion) VALUES " +
                        "('owner', 9, 'pub-9', 'CNY', 'CNY', 'ready', '餐饮', '缓存', 'thumbnails/9.jpg', 'none', " +
                        "'confirmed', '2026-05-13T00:00:00Z', 1)",
                )
                // Thumbnail present but deleted ⇒ no live image.
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, thumbnailPath, thumbnailDeletedAt, duplicateStatus, status, " +
                        "createdAt, rowVersion) VALUES ('owner', 10, 'pub-10', 'CNY', 'CNY', 'ready', '餐饮', '缓存', " +
                        "'thumbnails/10.jpg', '2026-05-01T00:00:00Z', 'none', 'confirmed', '2026-05-13T00:00:01Z', 1)",
                )
                // No thumbnail at all ⇒ nothing to infer from.
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion) VALUES " +
                        "('owner', 11, 'pub-11', 'CNY', 'CNY', 'ready', '餐饮', '缓存', 'none', 'confirmed', " +
                        "'2026-05-13T00:00:02Z', 1)",
                )
                AppDatabase.MIGRATION_14_15_STATEMENTS.forEach(st::execute)
            }

            val cols = conn.columns("expenses")
            assertTrue(cols.contains("categoryRaw"), "expenses must gain a categoryRaw column")
            assertTrue(cols.contains("hasImage"), "expenses must gain a hasImage column")
            conn.query("SELECT hasImage, categoryRaw FROM expenses WHERE serverId = 9") { rs ->
                assertTrue(rs.next(), "live-thumbnail row must survive")
                assertEquals(1L, rs.getLong(1), "live thumbnail backfills hasImage = 1")
                rs.getString(2)
                assertTrue(rs.wasNull(), "categoryRaw stays NULL for pre-v15 rows (falls back until resync)")
            }
            conn.query("SELECT hasImage FROM expenses WHERE serverId = 10") { rs ->
                assertTrue(rs.next())
                assertEquals(0L, rs.getLong(1), "deleted thumbnail does not count as a live image")
            }
            conn.query("SELECT hasImage FROM expenses WHERE serverId = 11") { rs ->
                assertTrue(rs.next())
                assertEquals(0L, rs.getLong(1), "no thumbnail defaults to hasImage = 0")
            }
        }
    }

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

            // pending_mutations: token column flips TEXT→INTEGER while the intent survives
            // as a review-required failure. It cannot be replayed with the stale timestamp.
            val outboxCols = conn.columns("pending_mutations")
            assertTrue(outboxCols.contains("expectedRowVersion"), "outbox token column must be expectedRowVersion")
            assertFalse(outboxCols.contains("expectedUpdatedAt"), "old expectedUpdatedAt column must be gone")
            conn.query(
                "SELECT type, targetId, payload, expectedRowVersion, status, lastError " +
                    "FROM pending_mutations WHERE id = 1",
            ) { rs ->
                assertTrue(rs.next(), "the pre-existing v10 outbox intent must survive")
                assertEquals("patch_expense", rs.getString(1))
                assertEquals("expense:9", rs.getString(2))
                assertEquals("{}", rs.getString(3))
                assertEquals(0L, rs.getLong(4))
                assertEquals("failed", rs.getString(5))
                assertEquals("legacy_concurrency_token_requires_review", rs.getString(6))
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

    @Test
    fun directMigration10To14PreservesLegacyIntentInQuarantine() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(v10Expenses)
                st.execute(v10PendingMutations)
                st.execute(
                    "INSERT INTO pending_mutations (serverUrl, ledgerId, type, targetId, payload, " +
                        "expectedUpdatedAt, status, createdAt) VALUES ('https://api.example.com', " +
                        "'owner', 'patch_expense', 'expense:9', '{\"merchant\":\"咖啡\"}', " +
                        "'2026-05-13T00:00:00Z', 'pending', '2026-05-13T00:00:00Z')",
                )
                AppDatabase.MIGRATION_10_11_STATEMENTS.forEach(st::execute)
                AppDatabase.MIGRATION_11_12_STATEMENTS.forEach(st::execute)
                AppDatabase.MIGRATION_12_13_STATEMENTS.forEach(st::execute)
                AppDatabase.MIGRATION_13_14_STATEMENTS.forEach(st::execute)
            }

            conn.query(
                "SELECT type, targetId, payload, expectedRowVersion, status, lastError, ownerKey " +
                    "FROM pending_mutations",
            ) { rs ->
                assertTrue(rs.next(), "the v10 intent must survive the complete upgrade chain")
                assertEquals("patch_expense", rs.getString(1))
                assertEquals("expense:9", rs.getString(2))
                assertEquals("{\"merchant\":\"咖啡\"}", rs.getString(3))
                assertEquals(0L, rs.getLong(4))
                assertEquals("failed", rs.getString(5))
                assertEquals("legacy_concurrency_token_requires_review", rs.getString(6))
                rs.getString(7)
                assertTrue(rs.wasNull(), "legacy URL and ledger data must not be promoted to an owner")
                assertFalse(rs.next(), "the migration must preserve exactly one seeded intent")
            }
        }
    }

    @Test
    fun migration11To12AddsNullableIdempotencyKeyPreservingRows() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(v11PendingMutations)
                // Seed a v11 outbox row — no idempotencyKey column exists yet.
                st.execute(
                    "INSERT INTO pending_mutations (serverUrl, ledgerId, type, targetId, payload, " +
                        "expectedRowVersion, status, createdAt) VALUES ('s', 'owner', 'patch_expense', " +
                        "'expense:9', '{}', 3, 'pending', '2026-05-13T00:00:00Z')",
                )
                AppDatabase.MIGRATION_11_12_STATEMENTS.forEach { st.execute(it) }
            }

            // Additive: idempotencyKey column added, pre-existing row survives with NULL.
            assertTrue(
                conn.columns("pending_mutations").contains("idempotencyKey"),
                "pending_mutations must gain an idempotencyKey column",
            )
            conn.query("SELECT idempotencyKey FROM pending_mutations WHERE targetId = 'expense:9'") { rs ->
                assertTrue(rs.next(), "the pre-existing v11 outbox row must survive the additive migration")
                rs.getString(1)
                assertTrue(rs.wasNull(), "migrated rows carry a NULL idempotencyKey (no key until Slice B)")
            }
        }
    }

    @Test
    fun migration12To13MakesServerIdNullableAndAddsClientRef() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(v12Expenses)
                // Seed a server-originated v12 row (no clientRef column yet).
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion) VALUES " +
                        "('owner', 9, 'pub-9', 'CNY', 'CNY', 'ready', '餐饮', '缓存', 'none', 'confirmed', " +
                        "'2026-05-13T00:00:00Z', 1)",
                )
                AppDatabase.MIGRATION_12_13_STATEMENTS.forEach { st.execute(it) }
            }

            // expenses gains clientRef; serverId is now nullable.
            assertTrue(conn.columns("expenses").contains("clientRef"), "expenses must gain a clientRef column")
            assertFalse(conn.columnNotNull("expenses", "serverId"), "serverId must be nullable after 12→13")

            // The pre-existing server row survives the rebuild with clientRef NULL.
            conn.query("SELECT clientRef FROM expenses WHERE serverId = 9") { rs ->
                assertTrue(rs.next(), "the pre-existing server row must survive the table rebuild")
                rs.getString(1)
                assertTrue(rs.wasNull(), "migrated rows carry a NULL clientRef")
            }

            // A local-only row (serverId NULL) is now insertable — proves nullability functionally,
            // which an offline manual create relies on.
            conn.createStatement().use { st ->
                st.execute(
                    "INSERT INTO expenses (ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode, " +
                        "fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion, clientRef) VALUES " +
                        "('owner', NULL, 'local-abc', 'CNY', 'CNY', 'ready', '餐饮', '手动记账', 'none', 'confirmed', " +
                        "'2026-05-13T00:01:00Z', 1, 'abc')",
                )
            }
            conn.query("SELECT COUNT(*) FROM expenses WHERE serverId IS NULL") { rs ->
                rs.next()
                assertEquals(1, rs.getInt(1), "a NULL-serverId local row must be insertable")
            }

            // All 7 expenses indices are rebuilt, including the new (ledgerId, clientRef) unique index.
            val indexNames = conn.indexNames("expenses")
            assertTrue(
                indexNames.contains("index_expenses_ledgerId_clientRef"),
                "the (ledgerId, clientRef) unique index must exist: $indexNames",
            )
            assertEquals(7, indexNames.size, "all 7 expenses indices must be present after the rebuild: $indexNames")
        }
    }

    @Test
    fun migration13To14PreservesRowsAsUnownedQuarantine() {
        Class.forName("org.sqlite.JDBC")
        DriverManager.getConnection("jdbc:sqlite::memory:").use { conn ->
            conn.createStatement().use { st ->
                st.execute(v11PendingMutations)
                AppDatabase.MIGRATION_11_12_STATEMENTS.forEach { st.execute(it) }
                st.execute(
                    "CREATE INDEX index_pending_mutations_serverUrl_ledgerId_createdAt " +
                        "ON pending_mutations (serverUrl, ledgerId, createdAt)",
                )
                st.execute(
                    "CREATE INDEX index_pending_mutations_serverUrl_ledgerId_targetId_status " +
                        "ON pending_mutations (serverUrl, ledgerId, targetId, status)",
                )
                st.execute(
                    "CREATE INDEX index_pending_mutations_serverUrl_ledgerId_status " +
                        "ON pending_mutations (serverUrl, ledgerId, status)",
                )
                st.execute(
                    "INSERT INTO pending_mutations (serverUrl, ledgerId, type, targetId, payload, " +
                        "expectedRowVersion, status, createdAt) VALUES ('https://old.example.com', " +
                        "'owner', 'create_expense', 'expense:local:abc', '{}', 0, 'pending', " +
                        "'2026-07-15T00:00:00.000Z')",
                )
                AppDatabase.MIGRATION_13_14_STATEMENTS.forEach { st.execute(it) }
            }

            assertTrue(conn.columns("pending_mutations").contains("ownerKey"))
            conn.query(
                "SELECT serverUrl, ledgerId, ownerKey FROM pending_mutations WHERE targetId = 'expense:local:abc'",
            ) { rs ->
                assertTrue(rs.next(), "the pre-existing offline intent must survive")
                assertEquals("https://old.example.com", rs.getString(1))
                assertEquals("owner", rs.getString(2))
                rs.getString(3)
                assertTrue(rs.wasNull(), "a URL-only row must not be assigned to the current identity")
            }

            val indices = conn.indexNames("pending_mutations")
            assertFalse(indices.any { "serverUrl_ledgerId" in it })
            assertTrue(indices.contains("index_pending_mutations_ownerKey_ledgerId_createdAt"))
            assertTrue(indices.contains("index_pending_mutations_ownerKey_ledgerId_targetId_status"))
            assertTrue(indices.contains("index_pending_mutations_ownerKey_ledgerId_status"))
        }
    }

    private fun Connection.columns(table: String): Set<String> {
        val cols = mutableSetOf<String>()
        query("PRAGMA table_info($table)") { rs -> while (rs.next()) cols += rs.getString("name") }
        return cols
    }

    private fun Connection.columnNotNull(table: String, column: String): Boolean {
        var notNull = false
        query("PRAGMA table_info($table)") { rs ->
            while (rs.next()) {
                if (rs.getString("name") == column) notNull = rs.getInt("notnull") == 1
            }
        }
        return notNull
    }

    private fun Connection.indexNames(table: String): List<String> {
        val names = mutableListOf<String>()
        query(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = '$table' AND name LIKE 'index_%'",
        ) { rs -> while (rs.next()) names += rs.getString("name") }
        return names
    }

    private inline fun <T> Connection.query(sql: String, block: (java.sql.ResultSet) -> T): T =
        createStatement().use { st -> st.executeQuery(sql).use(block) }
}
