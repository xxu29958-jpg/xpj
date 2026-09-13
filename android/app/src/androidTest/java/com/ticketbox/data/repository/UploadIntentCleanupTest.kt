package com.ticketbox.data.repository

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/** Every existing row-deletion entry must release only files whose last reference was removed. */
@RunWith(Parameterized::class)
class UploadIntentCleanupTest(private val entry: Entry) {
    enum class Entry { CONFLICT_DROP, FAILED_DROP, STOP, QUARANTINE, CLEAR_ALL, CLEAR_ON_BINDING, DONE_GC }

    @Test
    fun deletionReclaimsUnreferencedOriginalsAndPreservesEverySurvivingRow() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val request = fixture.request(listOf("removed.png"))
            val first = fixture.repository.acceptUploadBatch(request).getOrThrow()
            val original = fixture.dao.allRows().single()
            fixture.outbox.markDone(original.id)
            fixture.repository.acceptUploadBatch(fixture.request(listOf("retained.png"))).getOrThrow()
            val remaining = fixture.dao.allRows().last()
            val removable = when (entry) {
                Entry.CONFLICT_DROP -> original.copy(status = "conflict")
                Entry.FAILED_DROP -> original.copy(status = "failed")
                Entry.QUARANTINE -> original.copy(ownerKey = "another-owner")
                Entry.DONE_GC -> original.copy(status = "done", completedAt = "2026-09-06T00:00:00.000Z")
                else -> original
            }
            fixture.dao.clearAll()
            fixture.dao.insertBatch(listOf(removable, remaining))
            assertTrue(fixture.original(requireNotNull(original.idempotencyKey)).isFile)
            assertTrue(fixture.original(requireNotNull(remaining.idempotencyKey)).isFile)

            withTimeout(5_000) {
                when (entry) {
                    Entry.CONFLICT_DROP -> assertTrue(fixture.outbox.resolveConflict(original.id, ConflictResolution.DropMine))
                    Entry.FAILED_DROP -> assertTrue(fixture.outbox.resolveFailed(original.id, FailedResolution.Drop))
                    Entry.STOP -> fixture.repository.recoverUploadGroup(request.expectedBinding, first.groupId, true).getOrThrow()
                    Entry.QUARANTINE -> assertEquals(1, fixture.outbox.clearQuarantined())
                    Entry.CLEAR_ALL -> assertEquals(2, fixture.outbox.clearAll())
                    Entry.CLEAR_ON_BINDING -> fixture.outbox.withBindingTransition(clearExistingRows = true) {}
                    Entry.DONE_GC -> assertEquals(1, fixture.outbox.gcCompleted(retentionMillis = 0))
                }
            }

            val clearsAll = entry == Entry.CLEAR_ALL || entry == Entry.CLEAR_ON_BINDING
            assertEquals(if (clearsAll) emptyList() else listOf(remaining), fixture.dao.allRows())
            assertFalse(fixture.original(requireNotNull(original.idempotencyKey)).exists())
            assertEquals(!clearsAll, fixture.original(requireNotNull(remaining.idempotencyKey)).isFile)
            assertFalse(fixture.outbox.resolveFailed(original.id, FailedResolution.Drop))
            assertFalse(fixture.outbox.resolveConflict(original.id, ConflictResolution.DropMine))
            assertEquals(if (clearsAll) emptyList() else listOf(remaining), fixture.dao.allRows())
        }
    }

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun entries(): List<Array<Entry>> = Entry.entries.map { arrayOf(it) }
    }
}
