package com.ticketbox.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.ticketbox.domain.model.FxContract

@Database(
    entities = [ExpenseEntity::class, PendingMutationEntity::class],
    version = 12,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun expenseDao(): ExpenseDao
    abstract fun pendingMutationDao(): PendingMutationDao

    companion object {
        @Volatile
        private var instance: AppDatabase? = null

        private val Migration1To2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS expenses_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                        serverId INTEGER NOT NULL,
                        publicId TEXT NOT NULL,
                        amountCents INTEGER,
                        merchant TEXT,
                        category TEXT NOT NULL,
                        note TEXT,
                        source TEXT NOT NULL,
                        thumbnailPath TEXT,
                        imageHash TEXT,
                        rawText TEXT,
                        duplicateStatus TEXT NOT NULL,
                        duplicateOfId INTEGER,
                        duplicateReason TEXT,
                        tags TEXT,
                        valueScore INTEGER,
                        regretScore INTEGER,
                        status TEXT NOT NULL,
                        expenseTime TEXT,
                        createdAt TEXT NOT NULL,
                        confirmedAt TEXT,
                        updatedAt TEXT
                    )
                    """.trimIndent(),
                )
                db.execSQL(
                    """
                    INSERT INTO expenses_new (
                        id,
                        serverId,
                        publicId,
                        amountCents,
                        merchant,
                        category,
                        note,
                        source,
                        thumbnailPath,
                        imageHash,
                        rawText,
                        duplicateStatus,
                        duplicateOfId,
                        duplicateReason,
                        tags,
                        valueScore,
                        regretScore,
                        status,
                        expenseTime,
                        createdAt,
                        confirmedAt,
                        updatedAt
                    )
                    SELECT
                        id,
                        serverId,
                        'server-' || serverId,
                        amountCents,
                        merchant,
                        category,
                        note,
                        source,
                        thumbnailPath,
                        imageHash,
                        rawText,
                        duplicateStatus,
                        duplicateOfId,
                        duplicateReason,
                        tags,
                        valueScore,
                        regretScore,
                        status,
                        expenseTime,
                        createdAt,
                        confirmedAt,
                        updatedAt
                    FROM expenses
                    """.trimIndent(),
                )
                db.execSQL("DROP TABLE expenses")
                db.execSQL("ALTER TABLE expenses_new RENAME TO expenses")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_expenses_serverId ON expenses (serverId)")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_expenses_publicId ON expenses (publicId)")
            }
        }

        private val Migration2To3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE INDEX IF NOT EXISTS index_expenses_status_expenseTime ON expenses (status, expenseTime)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_expenses_status_confirmedAt ON expenses (status, confirmedAt)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_expenses_status_createdAt ON expenses (status, createdAt)")
            }
        }

        // v0.4-alpha1 multi-ledger foundation: every confirmed-cache row belongs to
        // a specific ledger. Existing rows are tagged with the sentinel ledgerId
        // 'legacy' and will be replaced the next time a token-bound ledger refreshes
        // its cache. We never use destructiveMigration.
        private val Migration3To4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE expenses ADD COLUMN ledgerId TEXT NOT NULL DEFAULT 'legacy'",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_expenses_ledgerId ON expenses (ledgerId)",
                )
            }
        }

        private val Migration4To5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE expenses ADD COLUMN originalCurrencyCode TEXT NOT NULL DEFAULT '${FxContract.HomeCurrency.storageKey}'")
                db.execSQL("ALTER TABLE expenses ADD COLUMN originalAmountMinor INTEGER")
                db.execSQL("ALTER TABLE expenses ADD COLUMN exchangeRateToCny TEXT")
                db.execSQL("ALTER TABLE expenses ADD COLUMN exchangeRateDate TEXT")
                db.execSQL("ALTER TABLE expenses ADD COLUMN exchangeRateSource TEXT")
                db.execSQL(
                    """
                    UPDATE expenses
                    SET originalAmountMinor = amountCents,
                        exchangeRateToCny = CASE WHEN amountCents IS NULL THEN NULL ELSE '${FxContract.BaseRateToHome}' END,
                        exchangeRateSource = CASE WHEN amountCents IS NULL THEN NULL ELSE '${FxContract.SourceBase}' END
                    WHERE originalCurrencyCode = '${FxContract.HomeCurrency.storageKey}'
                    """.trimIndent(),
                )
            }
        }

        private val Migration5To6 = object : Migration(5, 6) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE expenses ADD COLUMN homeCurrencyCode TEXT NOT NULL DEFAULT '${FxContract.HomeCurrency.storageKey}'")
                db.execSQL("ALTER TABLE expenses ADD COLUMN fxStatus TEXT NOT NULL DEFAULT '${FxContract.StatusReady}'")
            }
        }

        private val Migration6To7 = object : Migration(6, 7) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("DROP INDEX IF EXISTS index_expenses_serverId")
                db.execSQL(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS index_expenses_ledgerId_serverId
                    ON expenses (ledgerId, serverId)
                    """.trimIndent(),
                )
            }
        }

        private val Migration7To8 = object : Migration(7, 8) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE expenses ADD COLUMN imageDeletedAt TEXT")
                db.execSQL("ALTER TABLE expenses ADD COLUMN thumbnailDeletedAt TEXT")
                db.execSQL("ALTER TABLE expenses ADD COLUMN confidence REAL")
            }
        }

        // ADR-0038 PR-2f: offline outbox skeleton. New table only —
        // no ALTER on existing tables, no backfill needed. The
        // skeleton is landable without PR-2g (WorkManager drain) so
        // a partial roll-out leaves the queue empty rather than
        // wedged.
        private val Migration8To9 = object : Migration(8, 9) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS pending_mutations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                        type TEXT NOT NULL,
                        targetId TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        expectedUpdatedAt TEXT NOT NULL,
                        status TEXT NOT NULL,
                        retryCount INTEGER NOT NULL DEFAULT 0,
                        lastError TEXT,
                        createdAt TEXT NOT NULL,
                        attemptedAt TEXT,
                        completedAt TEXT
                    )
                    """.trimIndent(),
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_pending_mutations_createdAt ON pending_mutations (createdAt)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_pending_mutations_targetId_status ON pending_mutations (targetId, status)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_pending_mutations_status ON pending_mutations (status)",
                )
            }
        }

        private val Migration9To10 = object : Migration(9, 10) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE pending_mutations ADD COLUMN serverUrl TEXT NOT NULL DEFAULT ''")
                db.execSQL("ALTER TABLE pending_mutations ADD COLUMN ledgerId TEXT NOT NULL DEFAULT ''")
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_pending_mutations_serverUrl_ledgerId_createdAt ON pending_mutations (serverUrl, ledgerId, createdAt)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_pending_mutations_serverUrl_ledgerId_targetId_status ON pending_mutations (serverUrl, ledgerId, targetId, status)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_pending_mutations_serverUrl_ledgerId_status ON pending_mutations (serverUrl, ledgerId, status)",
                )
            }
        }

        // ADR-0041 phase-3 slice C: flip the optimistic-concurrency token from
        // the row's ``updated_at`` ISO string to the server-side ``row_version``
        // monotonic int. Two structural changes:
        //   1. expenses cache gains a ``rowVersion`` column (DEFAULT 1; the real
        //      value arrives on the next sync refresh).
        //   2. The outbox token column changes TEXT → INTEGER. SQLite can't ALTER
        //      a column type, and a string ``updated_at`` token captured by a
        //      pre-0041 build can't be replayed against the int-CAS backend, so
        //      the queue is dropped and rebuilt empty (no real install base
        //      during development — this is a destructive outbox reset by design).
        // SQL exposed as a list (not inline) so AppDatabaseMigrationSqlTest (JVM,
        // sqlite-jdbc) runs the EXACT production statements against in-memory
        // SQLite, while the instrumented AppDatabaseMigrationTest hands the
        // Migration10To11 object below to MigrationTestHelper and validates the
        // result against the exported 11.json on a device.
        internal val MIGRATION_10_11_STATEMENTS: List<String> = listOf(
            "ALTER TABLE expenses ADD COLUMN rowVersion INTEGER NOT NULL DEFAULT 1",
            "DROP TABLE IF EXISTS pending_mutations",
            """
            CREATE TABLE IF NOT EXISTS pending_mutations (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                serverUrl TEXT NOT NULL DEFAULT '',
                ledgerId TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL,
                targetId TEXT NOT NULL,
                payload TEXT NOT NULL,
                expectedRowVersion INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                retryCount INTEGER NOT NULL DEFAULT 0,
                lastError TEXT,
                createdAt TEXT NOT NULL,
                attemptedAt TEXT,
                completedAt TEXT
            )
            """.trimIndent(),
            "CREATE INDEX IF NOT EXISTS index_pending_mutations_createdAt ON pending_mutations (createdAt)",
            "CREATE INDEX IF NOT EXISTS index_pending_mutations_targetId_status ON pending_mutations (targetId, status)",
            "CREATE INDEX IF NOT EXISTS index_pending_mutations_status ON pending_mutations (status)",
            "CREATE INDEX IF NOT EXISTS index_pending_mutations_serverUrl_ledgerId_createdAt ON pending_mutations (serverUrl, ledgerId, createdAt)",
            "CREATE INDEX IF NOT EXISTS index_pending_mutations_serverUrl_ledgerId_targetId_status ON pending_mutations (serverUrl, ledgerId, targetId, status)",
            "CREATE INDEX IF NOT EXISTS index_pending_mutations_serverUrl_ledgerId_status ON pending_mutations (serverUrl, ledgerId, status)",
        )

        // internal (not private) so AppDatabaseMigrationTest can hand this exact
        // Migration to MigrationTestHelper.runMigrationsAndValidate.
        internal val Migration10To11 = object : Migration(10, 11) {
            override fun migrate(db: SupportSQLiteDatabase) {
                MIGRATION_10_11_STATEMENTS.forEach(db::execSQL)
            }
        }

        // ADR-0042 Slice A: add the request-idempotency key column to the
        // outbox. Nullable additive ALTER (no rebuild, no backfill) — Slice A is
        // groundwork (column + plumbing); the call sites that generate the
        // intent-time UUID land in Slice B+, so rows enqueued before then carry
        // NULL. Exposed as a list so AppDatabaseMigrationSqlTest (JVM,
        // sqlite-jdbc) runs the EXACT production statement, mirroring 10→11.
        internal val MIGRATION_11_12_STATEMENTS: List<String> = listOf(
            "ALTER TABLE pending_mutations ADD COLUMN idempotencyKey TEXT",
        )

        internal val Migration11To12 = object : Migration(11, 12) {
            override fun migrate(db: SupportSQLiteDatabase) {
                MIGRATION_11_12_STATEMENTS.forEach(db::execSQL)
            }
        }

        fun getDatabase(context: Context): AppDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "ticketbox.db",
                )
                    .addMigrations(
                        Migration1To2,
                        Migration2To3,
                        Migration3To4,
                        Migration4To5,
                        Migration5To6,
                        Migration6To7,
                        Migration7To8,
                        Migration8To9,
                        Migration9To10,
                        Migration10To11,
                        Migration11To12,
                    )
                    .build()
                    .also { instance = it }
            }
        }
    }
}
