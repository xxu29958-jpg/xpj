package com.ticketbox.data.local

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import java.io.Closeable
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Direct generated Room DAO tests. No fake queue, HTTP sender or status predicate. */
class PendingMutationUploadQueueTest {
    @Test
    fun receiptAndDoneAreOneDurableRowWithoutChangingTheOriginalCommand() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val original = fixture.row("first")
            val id = fixture.dao.insertBatch(listOf(original)).single()
            assertEquals(1, fixture.dao.markInFlightIfPending(id, "pending", "in_flight", ATTEMPTED))
            fixture.dao.markDone(id, "done", COMPLETED, RECEIPT)

            val stored = fixture.reopen().allRows().single()
            assertEquals(id, stored.id)
            assertEquals("done", stored.status)
            assertEquals(COMPLETED, stored.completedAt)
            assertEquals(RECEIPT, stored.receiptJson)
            assertEquals(original.idempotencyKey, stored.idempotencyKey)
            assertEquals(original.payload, stored.payload)
            assertEquals(original.expectedRowVersion, stored.expectedRowVersion)
            assertNull(stored.lastError)
        }
    }

    @Test
    fun ordinaryFailureRemainsVisibleWhileItsTailBecomesRunnableAfterReopen() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val originals = listOf(fixture.row("a"), fixture.row("b"), fixture.row("c"))
            val ids = fixture.dao.insertBatch(originals)
            assertEquals(listOf(ids[0]), runnable(fixture.dao).map { it.id })
            assertEquals(1, fixture.dao.markInFlightIfPending(ids[0], "pending", "in_flight", ATTEMPTED))
            fixture.dao.markDone(ids[0], "done", COMPLETED, RECEIPT)
            assertEquals(1, fixture.dao.markInFlightIfPending(ids[1], "pending", "in_flight", ATTEMPTED))
            fixture.dao.markFailed(ids[1], "failed", "ordinary_upload_failure", blocksFollowing = false)

            val dao = fixture.reopen()
            assertEquals(listOf(ids[2]), runnable(dao).map { it.id })
            val failed = dao.allRows().single { it.id == ids[1] }
            assertEquals("failed", failed.status)
            assertFalse(failed.blocksFollowing)
            assertEquals(originals[1].idempotencyKey, failed.idempotencyKey)
            assertEquals(originals[1].payload, failed.payload)
            assertFalse(dao.hasUnresolvedRowForTarget(OWNER, LEDGER, TARGET, UNRESOLVED))
        }
    }

    @Test
    fun defaultFailuresAndInFlightOrConflictEvenWithFalseFlagsStillBlock() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val old = fixture.row("old").copy(type = "patch_expense", targetId = "expense:42")
            val oldIds = fixture.dao.insertBatch(listOf(old, old.copy(idempotencyKey = "old-tail")))
            fixture.dao.markFailed(oldIds[0], "failed", "legacy_failure")
            val conflict = fixture.row("conflict").copy(targetId = "upload_batch:conflict", status = "conflict", blocksFollowing = false)
            val busy = fixture.row("busy").copy(targetId = "upload_batch:busy", status = "in_flight", blocksFollowing = false)
            fixture.dao.insertBatch(listOf(conflict, conflict.copy(status = "pending"), busy, busy.copy(status = "pending")))
            fixture.dao.insert(fixture.row("foreign").copy(ownerKey = "other-owner", status = "failed"))
            fixture.dao.insert(fixture.row("other-ledger").copy(ledgerId = "other-ledger", status = "failed"))
            val free = fixture.dao.insert(fixture.row("free"))

            assertEquals(listOf(free), runnable(fixture.dao).map { it.id })
            assertTrue(fixture.dao.allRows().single { it.id == oldIds[0] }.blocksFollowing)
            assertTrue(fixture.dao.hasUnresolvedRowForTarget(OWNER, LEDGER, old.targetId, UNRESOLVED))
            assertTrue(fixture.dao.hasUnresolvedRowForTarget(OWNER, LEDGER, conflict.targetId, UNRESOLVED))
            assertTrue(fixture.dao.hasUnresolvedRowForTarget(OWNER, LEDGER, busy.targetId, UNRESOLVED))
        }
    }

    @Test
    fun retryingTheEarlierFailureInvalidatesAnAlreadyDequeuedTailClaim() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val original = fixture.row("b").copy(status = "failed", blocksFollowing = false)
            val ids = fixture.dao.insertBatch(listOf(original, fixture.row("c")))
            val dequeued = runnable(fixture.dao).single()
            assertEquals(ids[1], dequeued.id)
            assertEquals(1, fixture.dao.retryFailed(ids[0], OWNER, LEDGER))

            assertEquals(0, fixture.dao.markInFlightIfPending(dequeued.id, "pending", "in_flight", ATTEMPTED))
            val tail = fixture.dao.allRows().single { it.id == dequeued.id }
            assertEquals("pending", tail.status)
            assertEquals(0, tail.retryCount)
            assertNull(tail.attemptedAt)
            assertEquals(1, fixture.dao.markInFlightIfPending(ids[0], "pending", "in_flight", ATTEMPTED))
            val earlier = fixture.dao.allRows().single { it.id == ids[0] }
            assertTrue(earlier.blocksFollowing)
            assertEquals(original.idempotencyKey, earlier.idempotencyKey)
            assertEquals(original.payload, earlier.payload)
            assertEquals(original.expectedRowVersion, earlier.expectedRowVersion)
        }
    }

    @Test
    fun failedBatchRollsBackAndReadsDistinguishBoundLookupFromAllReferences() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val original = fixture.row("original").copy(id = 100)
            fixture.dao.insert(original)
            val rejected = runCatching {
                fixture.dao.insertBatch(listOf(fixture.row("prefix").copy(id = 101), original))
            }.exceptionOrNull()
            assertNotNull(rejected)
            assertEquals(listOf(original), fixture.dao.allRows())
            val foreign = original.copy(id = 102, ownerKey = "other-owner")
            val unknown = original.copy(id = 103, ownerKey = null, type = "future_command", status = "future_status")
            fixture.dao.insertBatch(listOf(foreign, unknown))

            val matching = fixture.dao.findByIdempotencyKeys(OWNER, LEDGER, "upload_screenshot", listOf("original"))
            assertEquals(listOf(original), matching)
            assertEquals(listOf(original, foreign, unknown), fixture.dao.allRows())
        }
    }

    @Test
    fun uploadFreshTokenRecoveryCannotReplaceTheOriginalKeyOrBody() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val upload = fixture.row("original-upload").copy(status = "failed", blocksFollowing = false)
            val conflict = upload.copy(status = "conflict", idempotencyKey = "conflict-upload")
            val legacy = upload.copy(type = "patch_expense", targetId = "expense:42", idempotencyKey = "old-key")
            val ids = fixture.dao.insertBatch(listOf(upload, conflict, legacy))

            assertEquals(0, fixture.dao.requeueFailedWithFreshToken(ids[0], OWNER, LEDGER, 9L, "replacement"))
            assertEquals(0, fixture.dao.requeueConflictWithFreshToken(ids[1], OWNER, LEDGER, 9L, "replacement"))
            val unchanged = fixture.dao.allRows().first()
            assertEquals(upload.copy(id = ids[0]), unchanged)
            assertEquals(1, fixture.dao.requeueFailedWithFreshToken(ids[2], OWNER, LEDGER, 9L, "replacement"))
            val oldRecovery = fixture.dao.allRows().last()
            assertEquals(9L, oldRecovery.expectedRowVersion)
            assertEquals("replacement", oldRecovery.idempotencyKey)
            assertTrue(oldRecovery.blocksFollowing)
        }
    }

    @Test
    fun bothExpiryPathsRestoreBlockingWithoutDeletingOrRewritingIntent() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val pending = fixture.row("pending").copy(blocksFollowing = false)
            val failed = fixture.row("failed").copy(status = "failed", blocksFollowing = false)
            val ids = fixture.dao.insertBatch(listOf(pending, failed))
            assertEquals(1, fixture.dao.markExpiredPendingAsFailed("2026-09-01T00:00:00.000Z", "failed", "outbox_row_expired"))
            assertEquals(0, fixture.dao.expireBoundRowIfStatusAndOverAge(ids[1], "other-owner", LEDGER, "failed", COMPLETED))
            assertEquals(1, fixture.dao.expireBoundRowIfStatusAndOverAge(ids[1], OWNER, LEDGER, "failed", COMPLETED))

            val rows = fixture.reopen().allRows()
            assertEquals(2, rows.size)
            assertTrue(rows.all { it.blocksFollowing && it.status == "failed" && it.lastError == "outbox_row_expired" })
            assertEquals(listOf(pending.payload, failed.payload), rows.map { it.payload })
            assertEquals(listOf(pending.idempotencyKey, failed.idempotencyKey), rows.map { it.idempotencyKey })
            assertEquals(listOf(pending.expectedRowVersion, failed.expectedRowVersion), rows.map { it.expectedRowVersion })
        }
    }

    @Test
    fun excludingTriedRowsFindsOtherTargetsButDoesNotAdvanceTheirUnresolvedTail() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val ids = fixture.dao.insertBatch(listOf(
                fixture.row("b"), fixture.row("c"), fixture.row("other").copy(targetId = "upload_batch:other"),
            ))
            assertEquals(listOf(ids[0], ids[2]), runnable(fixture.dao).map { it.id })
            val remaining = fixture.dao.nextRunnableBatch(OWNER, LEDGER, UNRESOLVED, 1, listOf(ids[0]))
            assertEquals(listOf(ids[2]), remaining.map { it.id })
            assertEquals(0, fixture.dao.markInFlightIfPending(ids[1], "pending", "in_flight", ATTEMPTED))
            assertEquals(1, fixture.dao.markInFlightIfPending(ids[2], "pending", "in_flight", ATTEMPTED))
        }
    }

    @Test
    fun stopDeletesOnlyTheBoundUnfinishedUploadGroupAndPreservesEveryOtherOriginal() = runBlocking<Unit> {
        UploadQueueFixture().use { fixture ->
            val unfinished = listOf("pending", "in_flight", "conflict", "failed", "future_status")
                .map { status -> fixture.row(status).copy(status = status) }
            val preserved = listOf(
                fixture.row("delivered").copy(status = "done", receiptJson = RECEIPT, completedAt = COMPLETED),
                fixture.row("other-command").copy(type = "patch_expense"),
                fixture.row("other-owner").copy(ownerKey = "other-owner"),
                fixture.row("other-ledger").copy(ledgerId = "other-ledger"),
                fixture.row("other-group").copy(targetId = "upload_batch:other"),
                fixture.row("unowned").copy(ownerKey = null),
            )
            val ids = fixture.dao.insertBatch(unfinished + preserved)
            val originals = fixture.dao.allRows()
            assertEquals(0, fixture.dao.deleteUnfinishedUploadGroup("missing-owner", LEDGER, TARGET))
            assertEquals(originals, fixture.dao.allRows())

            assertEquals(unfinished.size, fixture.dao.deleteUnfinishedUploadGroup(OWNER, LEDGER, TARGET))
            val dao = fixture.reopen()
            assertEquals(preserved.mapIndexed { index, row -> row.copy(id = ids[unfinished.size + index]) }, dao.allRows())
            assertEquals(0, dao.deleteUnfinishedUploadGroup(OWNER, LEDGER, TARGET))
        }
    }

    private suspend fun runnable(dao: PendingMutationDao): List<PendingMutationEntity> =
        dao.nextRunnableBatch(OWNER, LEDGER, UNRESOLVED, 25)

    private companion object {
        const val OWNER = "original-owner"
        const val LEDGER = "family"
        const val TARGET = "upload_batch:original"
        const val ATTEMPTED = "2026-09-07T00:00:00.000Z"
        const val COMPLETED = "2026-09-07T00:00:01.000Z"
        val RECEIPT = """
            {"id":42,"public_id":"a55b5c26-7dc3-40bd-8af4-8e7aad041ec1",
             "enrichment_task_public_id":"21a81ad0-ae14-4ebd-bf50-7389cc5cb56b",
             "status":"pending","message":"queued",
             "image_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
             "thumbnail_path":null,"duplicate_status":"none","duplicate_of_id":null,
             "upload_size_bytes":3,"duration_ms":null,"timing_ms":null}
        """.trimIndent()
        val UNRESOLVED = listOf("in_flight", "conflict", "failed")
    }
}

private class UploadQueueFixture : Closeable {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "upload-queue-test-${UUID.randomUUID()}.db"
    private var database = open()
    val dao: PendingMutationDao get() = database.pendingMutationDao()

    private fun open(): AppDatabase = Room.databaseBuilder(context, AppDatabase::class.java, name).build()

    fun row(key: String): PendingMutationEntity = PendingMutationEntity(
        serverUrl = "https://example.test",
        ledgerId = "family",
        ownerKey = "original-owner",
        type = "upload_screenshot",
        targetId = "upload_batch:original",
        payload = "{\"original\":\"$key\"}",
        idempotencyKey = key,
        status = "pending",
        createdAt = "2026-08-01T00:00:00.000Z",
    )

    fun reopen(): PendingMutationDao {
        database.close()
        database = open()
        return dao
    }

    override fun close() {
        database.close()
        check(context.deleteDatabase(name))
    }
}
