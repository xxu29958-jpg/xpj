package com.ticketbox.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [ExpenseEntity::class],
    version = 3,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun expenseDao(): ExpenseDao

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

        fun getDatabase(context: Context): AppDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "ticketbox.db",
                )
                    .addMigrations(Migration1To2, Migration2To3)
                    .build()
                    .also { instance = it }
            }
        }
    }
}
