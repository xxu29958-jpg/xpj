package com.ticketbox.data.local

import androidx.room.testing.MigrationTestHelper
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * ADR-0041 P2 (review): the v10→v11 migration is install-upgrade-critical —
 * it adds ``expenses.rowVersion`` (DEFAULT 1) and rebuilds
 * ``pending_mutations`` with the new INTEGER ``expectedRowVersion`` column and
 * its 6 indices while preserving old intents as review-required failures.
 * Static schema alignment with 11.json was verified by hand,
 * but only a real [MigrationTestHelper] run exercises the actual migration SQL
 * against SQLite and validates the resulting schema against the exported
 * 11.json — catching upgrade crashes and schema/index drift the fake-DAO unit
 * suite (which never opens Room) cannot.
 */
class AppDatabaseMigrationTest {
    @Test fun migrate24To25KeepsExistingInputAndPersistsOriginalMerchantCreationAcrossReopen() {
        val name = "migration-24-25-merchant-input.db"
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        helper.createDatabase(name, 24).use { db ->
            db.execSQL("INSERT INTO expense_fact_inputs VALUES ('original-owner','owner',9,'correction','binding','fact-key','raw-fact-input')")
        }
        helper.runMigrationsAndValidate(name, 25, true, AppDatabase.Migration24To25).use { db ->
            db.query("SELECT originalKey, inputJson FROM expense_fact_inputs").use {
                assertTrue(it.moveToFirst()); assertEquals("fact-key", it.getString(0)); assertEquals("raw-fact-input", it.getString(1))
            }
        }
        val binding = com.ticketbox.data.repository.LogicalSessionBinding("https://isolated.invalid", "owner", "original-owner", "session", "revision")
        val input = com.ticketbox.data.repository.MerchantDraft(binding,
            com.ticketbox.data.repository.MerchantDraftKind.Alias, "original-create-key",
            canonicalMerchant = "  原标准商家  ", alias = "  原别名  ", phase = "unconfirmed")
        val source = com.ticketbox.domain.model.MerchantCatalog("source", "原商家", "原商家", "active", null, 2,
            "2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z", 7, null)
        val rename = com.ticketbox.data.repository.MerchantDraft(binding, com.ticketbox.data.repository.MerchantDraftKind.Rename,
            "original-rename-key", displayName = "  原改名  ", source = source)
        val otherRename = rename.copy(key = "other-rename-key", source = source.copy(publicId = "other"), displayName = "  另一原稿  ")
        val firstSource = com.ticketbox.data.remote.dto.MerchantCatalogDto("source", "原商家", "原商家", "merged", "target", 2,
            "2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z", 8)
        val firstReceipt = com.ticketbox.data.remote.dto.MerchantCatalogMergeDto(firstSource,
            firstSource.copy(publicId = "target", status = "active", mergedIntoPublicId = null, rowVersion = 12), null)
        val merge = rename.copy(kind = com.ticketbox.data.repository.MerchantDraftKind.Merge, key = "original-merge-key",
            target = source.copy(publicId = "target", rowVersion = 11), aliasPolicy = com.ticketbox.domain.model.MerchantCatalogAliasPolicy.None,
            parentRenameKey = rename.key, phase = "accepted", mergeReceipt = firstReceipt)
        val originals = setOf(input, rename, otherRename, merge)
        var room = androidx.room.Room.databaseBuilder(context, AppDatabase::class.java, name).build()
        try {
            kotlinx.coroutines.runBlocking {
                room.merchantCreationInputDao().put(MerchantCreationInputEntity(binding.serverUrl, binding.ownerKey, binding.ledgerId,
                    "Alias", input.key, """{"binding":{"serverUrl":"https://isolated.invalid","ledgerId":"owner","ownerKey":"original-owner",
                    "sessionGeneration":"session","bindingRevision":"revision"},"kind":"Alias","key":"original-create-key",
                    "displayName":"","canonicalMerchant":"  原标准商家  ","alias":"  原别名  ","phase":"unconfirmed"}"""))
                com.ticketbox.data.repository.MerchantDraftStore(room.merchantCreationInputDao()).writeAll(listOf(rename, otherRename, merge))
            }
            room.close()
            room = androidx.room.Room.databaseBuilder(context, AppDatabase::class.java, name).build()
            kotlinx.coroutines.runBlocking {
                val store = com.ticketbox.data.repository.MerchantDraftStore(room.merchantCreationInputDao())
                assertEquals(originals, store.read(binding).toSet())
                assertTrue(store.read(binding.copy(ownerKey = "another-owner")).isEmpty())
                assertTrue(store.read(binding.copy(ledgerId = "another-ledger")).isEmpty())
                assertTrue(store.read(binding.copy(serverUrl = "https://another.invalid")).isEmpty())
                store.remove(input.copy(key = "not-original"))
                assertEquals(originals, store.read(binding).toSet())
                store.acknowledge(merge)
                assertEquals(setOf(input, otherRename), store.read(binding).toSet())
            }
        } finally {
            room.close()
            context.deleteDatabase(name)
        }
    }

    @Test fun migrate23To24PreservesTheFactAndOriginalCommandBesideSeparateInputAndQueryStores() {
        val name = "migration-23-24-fact-continuity.db"
        helper.createDatabase(name, 23).use { db ->
            db.execSQL("""INSERT INTO expenses (id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                originalCurrencyCode, fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion)
                VALUES (1, 'owner', 9, 'fact-original', 1234, 'CNY', 'CNY', 'ready', '其他', '手动记账', 'none',
                    'confirmed', '2026-09-30T00:00:00Z', 7)""")
            db.execSQL("""INSERT INTO pending_mutations (serverUrl, ledgerId, ownerKey, type, targetId, payload,
                expectedRowVersion, status, retryCount, createdAt, idempotencyKey)
                VALUES ('https://isolated.invalid', 'owner', 'original-owner', 'correct_expense', 'expense:9',
                    '{"reason":"original"}', 7, 'pending', 2, '2026-09-30T00:00:00Z', 'original-key')""")
        }
        helper.runMigrationsAndValidate(name, 24, true, AppDatabase.Migration23To24).use { db ->
            db.query("SELECT amountCents, rowVersion FROM expenses WHERE serverId = 9").use {
                assertTrue(it.moveToFirst()); assertEquals(1234L, it.getLong(0)); assertEquals(7L, it.getLong(1))
            }
            db.query("SELECT payload, expectedRowVersion, idempotencyKey, status, retryCount FROM pending_mutations").use {
                assertTrue(it.moveToFirst()); assertEquals("{\"reason\":\"original\"}", it.getString(0))
                assertEquals(7L, it.getLong(1)); assertEquals("original-key", it.getString(2))
                assertEquals("pending", it.getString(3)); assertEquals(2, it.getInt(4))
            }
            db.execSQL("INSERT INTO expense_fact_inputs VALUES ('original-owner','owner',9,'correction','binding','draft-key','raw')")
            db.execSQL("INSERT INTO expense_fact_query_cache VALUES ('binding','owner',9,'bundle','history','2026-09-30T00:00:00Z')")
        }
    }

    @Test fun migrate22To23PreservesOriginalCommandsAndAddsOnlyReviewInputStorage() {
        val name = "migration-22-23-review.db"
        helper.createDatabase(name, 22).use { db ->
            db.execSQL("""INSERT INTO pending_mutations (serverUrl, ledgerId, ownerKey, type, targetId, payload,
                expectedRowVersion, status, retryCount, createdAt, idempotencyKey)
                VALUES ('https://isolated.invalid', 'original-ledger', 'original-owner', 'record_debt_repayment',
                'debt:original', '{"original":true}', 7, 'pending', 2, '2026-09-01T00:00:00Z', 'original-key')""")
        }
        helper.runMigrationsAndValidate(name, 23, true, AppDatabase.Migration22To23).use { db ->
            db.query("SELECT payload, expectedRowVersion, idempotencyKey, status, retryCount FROM pending_mutations").use {
                assertTrue(it.moveToFirst()); assertEquals("{\"original\":true}", it.getString(0))
                assertEquals(7, it.getInt(1)); assertEquals("original-key", it.getString(2))
                assertEquals("pending", it.getString(3)); assertEquals(2, it.getInt(4))
            }
        }
    }

    @Test fun migrate21To22PreservesFinancialFactsAndAddsIsolatedArrangementCache() {
        val name = "migration-21-22-arrangement.db"
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        helper.createDatabase(name, 21).use { db ->
            db.execSQL("""
                INSERT INTO expenses (id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion)
                VALUES (1, 'owner', 9, 'original-arrangement-neighbor', 100, 'JPY', 'JPY', 'ready', '其他', '手动记账', 'none',
                    'confirmed', '2026-09-27T00:00:00Z', 7)
            """.trimIndent())
        }
        val room = androidx.room.Room.databaseBuilder(context, AppDatabase::class.java, name)
            .addMigrations(AppDatabase.Migration21To22, AppDatabase.Migration22To23, AppDatabase.Migration23To24, AppDatabase.Migration24To25).build()
        try {
                room.openHelper.readableDatabase.query("SELECT amountCents, homeCurrencyCode, rowVersion FROM expenses WHERE id = 1").use {
                    assertTrue(it.moveToFirst()); assertEquals(100, it.getInt(0)); assertEquals("JPY", it.getString(1)); assertEquals(7, it.getInt(2))
                }
                kotlinx.coroutines.runBlocking {
                    val dao = room.monthlyArrangementCacheDao()
                    dao.write(MonthlyArrangementCacheEntity("household-a", "2026-09", "draft", "raw-input"))
                    dao.write(MonthlyArrangementCacheEntity("household-a", "2026-09", "saved", "confirmed-projection"))
                    assertEquals("raw-input", dao.read("household-a", "2026-09", "draft")?.json)
                    assertEquals("confirmed-projection", dao.read("household-a", "2026-09", "saved")?.json)
                    assertEquals(null, dao.read("household-b", "2026-09", "draft"))
                }
        } finally {
            room.close()
            context.deleteDatabase(name)
        }
    }

    @Test fun migrate20To21AddsUnknownEvidenceWithoutChangingTheFactVersion() {
        val name = "migration-20-21-test.db"
        helper.createDatabase(name, 20).use { db ->
            db.execSQL("""
                INSERT INTO expenses (id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion)
                VALUES (1, 'owner', 9, 'original', 100, 'CNY', 'CNY', 'ready', '其他', '手动记账', 'none',
                    'confirmed', '2026-05-01T00:00:00Z', 7)
            """.trimIndent())
        }
        helper.runMigrationsAndValidate(name, 21, true, AppDatabase.Migration20To21).use { db ->
            db.query("SELECT rowVersion, accountingDate, calendarRevision, timePrecision FROM expenses WHERE id = 1").use {
                assertTrue(it.moveToFirst())
                assertEquals(7, it.getInt(0))
                assertTrue(it.isNull(1) && it.isNull(2) && it.isNull(3))
            }
        }
    }

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
        // The timestamp token cannot replay against int CAS, but the financial
        // intent remains available for explicit review instead of disappearing.
        db.query(
            "SELECT type, targetId, payload, expectedRowVersion, status, lastError " +
                "FROM pending_mutations WHERE targetId = 'expense:9'",
        ).use { cursor ->
            assertTrue("migrated outbox intent must survive", cursor.moveToFirst())
            assertEquals("patch_expense", cursor.getString(0))
            assertEquals("expense:9", cursor.getString(1))
            assertEquals("{}", cursor.getString(2))
            assertEquals(0L, cursor.getLong(3))
            assertEquals("failed", cursor.getString(4))
            assertEquals("legacy_concurrency_token_requires_review", cursor.getString(5))
        }
    }

    @Test
    fun migrate11To12AddsNullableIdempotencyKey() {
        // ADR-0042 Slice A: v11→v12 is an additive ALTER (ADD COLUMN
        // idempotencyKey TEXT). The emulator-free AppDatabaseMigrationSqlTest
        // runs the raw SQL; this run applies Migration11To12 and validates the
        // result against the exported 12.json on a device, then asserts a seeded
        // v11 outbox row survives with a NULL key (no key until Slice B).
        val name = "migration-11-12-test.db"
        helper.createDatabase(name, 11).use { db ->
            db.execSQL(
                """
                INSERT INTO pending_mutations (
                    serverUrl, ledgerId, type, targetId, payload, expectedRowVersion,
                    status, retryCount, createdAt
                ) VALUES (
                    'https://api.example.com', 'owner', 'patch_expense', 'expense:9',
                    '{}', 3, 'pending', 0, '2026-05-13T00:00:00Z'
                )
                """.trimIndent(),
            )
        }

        val db = helper.runMigrationsAndValidate(
            name,
            12,
            true,
            AppDatabase.Migration11To12,
        )

        db.query(
            "SELECT idempotencyKey FROM pending_mutations WHERE targetId = 'expense:9'",
        ).use { cursor ->
            assertTrue("migrated v11 outbox row must survive", cursor.moveToFirst())
            assertTrue("idempotencyKey defaults to NULL", cursor.isNull(0))
        }
    }

    @Test
    fun migrate12To13MakesServerIdNullableAndAddsClientRef() {
        // issue #65 slice 4: v12→v13 rebuilds expenses to make serverId NULLABLE
        // and add clientRef + a (ledgerId, clientRef) unique index — so an offline
        // manual create can exist locally before it has a server id. The
        // emulator-free AppDatabaseMigrationSqlTest runs the raw SQL; this run
        // applies Migration12To13 and validates the rebuilt schema against the
        // exported 13.json on a device (the table-rebuild recipe is the part most
        // likely to drift from Room's expected TableInfo), then asserts a seeded
        // v12 row survives with a NULL clientRef.
        val name = "migration-12-13-test.db"
        helper.createDatabase(name, 12).use { db ->
            db.execSQL(
                """
                INSERT INTO expenses (
                    id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, merchant, category, source,
                    duplicateStatus, status, createdAt, rowVersion
                ) VALUES (
                    1, 'owner', 9, 'pub-9', 1500, 'CNY',
                    'CNY', 'ready', '星巴克', '餐饮', '缓存',
                    'none', 'confirmed', '2026-05-13T00:00:00Z', 1
                )
                """.trimIndent(),
            )
        }

        val db = helper.runMigrationsAndValidate(
            name,
            13,
            true,
            AppDatabase.Migration12To13,
        )

        // The pre-existing server row survives the rebuild with a NULL clientRef.
        db.query("SELECT clientRef FROM expenses WHERE serverId = 9").use { cursor ->
            assertTrue("migrated expenses row must survive the rebuild", cursor.moveToFirst())
            assertTrue("clientRef defaults to NULL for server rows", cursor.isNull(0))
        }
        // serverId is now nullable: a local-only row (NULL serverId) is insertable.
        db.execSQL(
            """
            INSERT INTO expenses (
                ledgerId, serverId, publicId, homeCurrencyCode, originalCurrencyCode,
                fxStatus, category, source, duplicateStatus, status, createdAt, rowVersion, clientRef
            ) VALUES (
                'owner', NULL, 'local-abc', 'CNY', 'CNY',
                'ready', '餐饮', '手动记账', 'none', 'confirmed', '2026-05-13T00:01:00Z', 1, 'abc'
            )
            """.trimIndent(),
        )
        db.query("SELECT COUNT(*) FROM expenses WHERE serverId IS NULL").use { cursor ->
            assertTrue(cursor.moveToFirst())
            assertEquals("a NULL-serverId local row must be insertable", 1L, cursor.getLong(0))
        }
    }

    @Test
    fun migrate14To15AddsQualityColumnsBackfillingFromThumbnails() {
        val name = "migration-14-15-test.db"
        helper.createDatabase(name, 14).use { db ->
            db.execSQL(
                """
                INSERT INTO expenses (
                    id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, merchant, category, source, thumbnailPath,
                    duplicateStatus, status, createdAt, rowVersion
                ) VALUES (
                    1, 'owner', 9, 'pub-9', 1500, 'CNY',
                    'CNY', 'ready', '星巴克', '餐饮', '缓存', 'thumbnails/9.jpg',
                    'none', 'confirmed', '2026-05-13T00:00:00Z', 1
                )
                """.trimIndent(),
            )
            db.execSQL(
                """
                INSERT INTO expenses (
                    id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, merchant, category, source,
                    duplicateStatus, status, createdAt, rowVersion
                ) VALUES (
                    2, 'owner', 10, 'pub-10', 800, 'CNY',
                    'CNY', 'ready', '麦当劳', '餐饮', '缓存',
                    'none', 'confirmed', '2026-05-13T00:01:00Z', 1
                )
                """.trimIndent(),
            )
        }

        val db = helper.runMigrationsAndValidate(
            name,
            15,
            true,
            AppDatabase.Migration14To15,
        )

        db.query("SELECT hasImage, categoryRaw FROM expenses WHERE serverId = 9").use { cursor ->
            assertTrue("the seeded row must survive migration", cursor.moveToFirst())
            assertEquals("live thumbnail backfills hasImage = 1", 1L, cursor.getLong(0))
            assertTrue("categoryRaw stays NULL until the next sync rewrite", cursor.isNull(1))
        }
        db.query("SELECT hasImage FROM expenses WHERE serverId = 10").use { cursor ->
            assertTrue(cursor.moveToFirst())
            assertEquals("no thumbnail defaults to hasImage = 0", 0L, cursor.getLong(0))
        }
    }

    @Test
    fun migrate15To16AddsFactRevisionWithoutLosingConfirmedRows() {
        val name = "migration-15-16-test.db"
        helper.createDatabase(name, 15).use { db ->
            db.execSQL(
                """
                INSERT INTO expenses (
                    id, ledgerId, serverId, publicId, amountCents, homeCurrencyCode,
                    originalCurrencyCode, fxStatus, merchant, category, source,
                    duplicateStatus, status, createdAt, rowVersion, hasImage
                ) VALUES (
                    1, 'owner', 9, 'pub-9', 1500, 'CNY',
                    'CNY', 'ready', '星巴克', '餐饮', '缓存',
                    'none', 'confirmed', '2026-08-28T00:00:00Z', 4, 1
                )
                """.trimIndent(),
            )
        }

        val db = helper.runMigrationsAndValidate(
            name,
            16,
            true,
            AppDatabase.Migration15To16,
        )

        db.query("SELECT rowVersion, factRevision FROM expenses WHERE serverId = 9").use { cursor ->
            assertTrue("the confirmed cache row must survive", cursor.moveToFirst())
            assertEquals(4L, cursor.getLong(0))
            assertEquals("legacy cache starts before revision history is synced", 0L, cursor.getLong(1))
        }
    }

    @Test
    fun migrate13To14PreservesLegacyIntentWithoutGuessingOwner() {
        val name = "migration-13-14-test.db"
        helper.createDatabase(name, 13).use { db ->
            db.execSQL(
                """
                INSERT INTO pending_mutations (
                    serverUrl, ledgerId, type, targetId, payload, expectedRowVersion,
                    status, retryCount, createdAt
                ) VALUES (
                    'https://old.example.com', 'owner', 'create_expense', 'expense:local:abc',
                    '{}', 0, 'pending', 0, '2026-07-15T00:00:00.000Z'
                )
                """.trimIndent(),
            )
        }

        val db = helper.runMigrationsAndValidate(
            name,
            14,
            true,
            AppDatabase.Migration13To14,
        )

        db.query(
            "SELECT serverUrl, ledgerId, ownerKey FROM pending_mutations WHERE targetId = 'expense:local:abc'",
        ).use { cursor ->
            assertTrue("the offline intent must survive migration", cursor.moveToFirst())
            assertEquals("https://old.example.com", cursor.getString(0))
            assertEquals("owner", cursor.getString(1))
            assertTrue("URL-only ownership must remain quarantined", cursor.isNull(2))
        }
    }

    @Test
    fun migrate17To18KeepsOriginalIntentAndDefaultsToNoReceiptAndBlockingFailure() {
        val name = "migration-17-18-upload-test.db"
        helper.createDatabase(name, 17).use { db ->
            db.execSQL(
                """
                INSERT INTO pending_mutations (
                    serverUrl, ledgerId, ownerKey, type, targetId, payload, expectedRowVersion,
                    idempotencyKey, status, retryCount, lastError, createdAt
                ) VALUES (
                    'https://example.test', 'family', NULL, 'patch_expense', 'expense:9',
                    '{"original":true}', 7, 'original-key', 'failed', 2,
                    'original_failure', '2026-08-01T00:00:00.000Z'
                )
                """.trimIndent(),
            )
        }

        helper.runMigrationsAndValidate(name, 18, true, AppDatabase.Migration17To18).use { db ->
            db.query(
                "SELECT receiptJson, blocksFollowing, ownerKey, payload, idempotencyKey, " +
                    "expectedRowVersion, status, retryCount, lastError FROM pending_mutations",
            ).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertTrue(cursor.isNull(0))
                assertEquals(1L, cursor.getLong(1))
                assertTrue(cursor.isNull(2))
                assertEquals("{\"original\":true}", cursor.getString(3))
                assertEquals("original-key", cursor.getString(4))
                assertEquals(7L, cursor.getLong(5))
                assertEquals("failed", cursor.getString(6))
                assertEquals(2L, cursor.getLong(7))
                assertEquals("original_failure", cursor.getString(8))
            }
        }
    }
}
