package com.ticketbox.data.local

import android.app.Application
import androidx.room.Room
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import java.io.File
import java.util.UUID
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class DebtBillInputMigrationRoomTest {
    @Test fun upgrades31KeepingFactsFilesAndCommands() {
        val context: Application = RuntimeEnvironment.getApplication()
        val name = "migration31-${UUID.randomUUID()}.db"
        val original = File(context.filesDir, "old-original-${UUID.randomUUID()}.png").apply { writeBytes(byteArrayOf(4, 5, 6)) }
        val oldSchema = sequenceOf(File("schemas"), File("app/schemas")).map {
            File(it, "com.ticketbox.data.local.AppDatabase/31.json") }.first(File::isFile)
        val schema = JSONObject(oldSchema.readText()).getJSONObject("database")
        val helper = FrameworkSQLiteOpenHelperFactory().create(SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(name).callback(object : SupportSQLiteOpenHelper.Callback(31) {
                override fun onCreate(db: SupportSQLiteDatabase) = createReleasedSchema(db, schema)
                override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = error("unexpected upgrade")
            }).build())
        val raw = """{"revision":1,"principal_amount_cents":1200,"original":" unchanged "}"""
        helper.writableDatabase.apply {
            execSQL("""INSERT INTO pending_mutations (serverUrl,ledgerId,ownerKey,type,targetId,payload,expectedRowVersion,
                status,retryCount,createdAt,idempotencyKey,receiptJson) VALUES ('https://old.invalid','owner','old-actor',
                'create_debt','debt:old',?,0,'done',2,'2026-10-01T00:00:00Z','old-key','{"accepted":true}')""", arrayOf(raw))
            execSQL("""INSERT INTO expenses (id,ledgerId,serverId,publicId,amountCents,homeCurrencyCode,originalCurrencyCode,
                fxStatus,category,source,duplicateStatus,status,createdAt,rowVersion,thumbnailPath) VALUES
                (1,'owner',9,'old-expense',1200,'CNY','CNY','ready','其他','截图','none','confirmed','2026-10-01',7,?)""",
                arrayOf(original.absolutePath))
        }
        helper.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).addMigrations(AppDatabase.Migration31To32).build()
        try {
                db.openHelper.readableDatabase.query("SELECT payload,idempotencyKey,receiptJson,expectedRowVersion FROM pending_mutations").use {
                    assertTrue(it.moveToFirst()); assertEquals(raw, it.getString(0)); assertEquals("old-key", it.getString(1))
                    assertEquals("{\"accepted\":true}", it.getString(2)); assertEquals(0, it.getInt(3))
                }
                db.openHelper.readableDatabase.query("SELECT amountCents,rowVersion,thumbnailPath FROM expenses").use {
                    assertTrue(it.moveToFirst()); assertEquals(1200L, it.getLong(0)); assertEquals(7L, it.getLong(1))
                    assertEquals(original.absolutePath, it.getString(2))
                }
                db.openHelper.readableDatabase.query("SELECT COUNT(*) FROM debt_bill_inputs").use {
                    assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                }
                assertEquals(32, db.openHelper.readableDatabase.version)
                assertContentEquals(byteArrayOf(4, 5, 6), original.readBytes())
        } finally { db.close(); context.deleteDatabase(name); original.delete() }
    }

    private fun createReleasedSchema(db: SupportSQLiteDatabase, schema: JSONObject) {
        val entities = schema.getJSONArray("entities")
        for (index in 0 until entities.length()) {
            val entity = entities.getJSONObject(index)
            val name = entity.getString("tableName")
            db.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}", name))
            val indices = entity.optJSONArray("indices") ?: org.json.JSONArray()
            for (item in 0 until indices.length()) db.execSQL(indices.getJSONObject(item).getString("createSql").replace("\${TABLE_NAME}", name))
        }
        val setup = schema.getJSONArray("setupQueries")
        for (index in 0 until setup.length()) db.execSQL(setup.getString(index))
    }
}
