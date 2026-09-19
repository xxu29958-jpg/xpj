package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue

class OriginalAttachmentRepositoryTest {
    @Test fun committedAdmissionLossReopensSameRawOriginalAndKeepsItDuringOrdinaryUploadGc() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val key = UUID.randomUUID().toString()
            val image = fixture.image("unaltered-original.png")
            val payload = OriginalAttachmentPayload(operation = "replenish_original", expenseId = 8, publicId = "expense-8",
                expectedRowVersion = 4, origin = requireNotNull(fixture.repository.currentOriginalBinding()), sha256 = "a".repeat(64))
            var reads = 0
            val request = OriginalSubmission(key, payload) { reads++; image }
            fixture.loseNextInsertAcknowledgement = true
            assertTrue(fixture.repository.submitOriginal(request).isFailure)
            val original = fixture.dao.allRows().single()
            fixture.reopen()
            assertEquals(original.id, fixture.repository.submitOriginal(request).getOrThrow())
            assertEquals(1, reads)
            assertEquals(PendingMutationType.OriginalAttachment.wireValue, original.type)
            assertEquals("expense:8", original.targetId)
            assertEquals(4L, original.expectedRowVersion)
            fixture.repository.collectOrphans()
            val retained = requireNotNull(readOriginalPayload(original.toDomain())?.file)
            assertArrayEquals(image.bytes, fixture.fileStore.read(retained))
            assertEquals(original, fixture.dao.allRows().single())
            assertTrue(fixture.savedTimestamps.isEmpty())
            assertEquals(0, fixture.apiCalls)
        }
    }
}
