package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import java.util.UUID
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse

class OriginalAttachmentRepositoryTest {
    @Test fun missingCapabilityRefusesAdmissionBeforeReadingSourceOrInsertingRoom() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            fixture.originalAttachmentVersion = null
            val payload = OriginalAttachmentPayload(operation = "replenish_original", expenseId = 8, publicId = "expense-8",
                expectedRowVersion = 4, origin = requireNotNull(fixture.repository.currentOriginalBinding()), sha256 = "a".repeat(64))
            val result = fixture.repository.submitOriginal(OriginalSubmission(UUID.randomUUID().toString(), payload) {
                error("Unsupported server must not prepare an original")
            })
            assertEquals("runtime_version_mismatch", (result.exceptionOrNull() as RepositoryException).errorCode)
            assertTrue(fixture.dao.allRows().isEmpty())
            assertEquals(0, fixture.apiCalls)
        }
    }

    @Test fun insertFailureOrCancellationReclaimsBytesWithoutAReference() = runBlocking<Unit> {
        for (failure in listOf(IOException("Room failed before commit"), CancellationException("Room insert cancelled"))) {
            UploadIntentRepositoryFixture().use { fixture ->
                val key = UUID.randomUUID().toString()
                val payload = OriginalAttachmentPayload(operation = "replenish_original", expenseId = 8, publicId = "expense-8",
                    expectedRowVersion = 4, origin = requireNotNull(fixture.repository.currentOriginalBinding()), sha256 = "a".repeat(64))
                fixture.nextInsertFailure = failure
                val result = runCatching { fixture.repository.submitOriginal(OriginalSubmission(key, payload) {
                    fixture.image("unadmitted.png")
                }).getOrThrow() }
                assertTrue(result.isFailure)
                assertTrue(fixture.dao.allRows().isEmpty())
                assertFalse(fixture.original(key).exists())
            }
        }
    }

    @Test fun writerLossAfterPreparingBytesReclaimsUnadmittedOriginal() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val key = UUID.randomUUID().toString()
            val payload = OriginalAttachmentPayload(operation = "replenish_original", expenseId = 8, publicId = "expense-8",
                expectedRowVersion = 4, origin = requireNotNull(fixture.repository.currentOriginalBinding()), sha256 = "a".repeat(64))
            val result = fixture.repository.submitOriginal(OriginalSubmission(key, payload) {
                fixture.session.value = fixture.session.value.copy(identity = fixture.session.value.identity.copy(role = "viewer"))
                fixture.image("unadmitted.png")
            })
            assertTrue(result.isFailure)
            assertTrue(fixture.dao.allRows().isEmpty())
            assertFalse(fixture.original(key).exists())
        }
    }

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
