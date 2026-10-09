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
    @Test fun selectionReopensWithoutEnqueueAndTransfersAtomicallyDespiteAdmissionReplyLoss() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val key = UUID.randomUUID().toString()
            val origin = requireNotNull(fixture.repository.currentOriginalBinding())
            val payload = OriginalAttachmentPayload(operation = "attach_original", expenseId = 8, publicId = "expense-8",
                expectedRowVersion = 4, origin = origin)
            val image = fixture.image("selected.png")
            fixture.repository.originalSelections.retainOriginalSelection(OriginalSubmission(key, payload) { image }).getOrThrow()
            assertTrue(fixture.dao.allRows().isEmpty())
            fixture.reopen()
            val draft = requireNotNull(fixture.repository.originalSelections.loadOriginalSelection(origin, 8).getOrThrow())
            assertEquals(key, draft.key)
            assertEquals(payload, draft.payload.copy(file = null))
            fixture.repository.collectOrphans()
            assertArrayEquals(image.bytes, fixture.repository.originalSelections.readOriginalSelection(draft).getOrThrow().bytes)
            val request = OriginalSubmission(key, draft.payload, draft) { error("Never reread a provider") }
            fixture.nextInsertFailure = IOException("Before Room admission")
            assertTrue(fixture.repository.submitOriginal(request).isFailure)
            assertTrue(fixture.dao.allRows().isEmpty())
            assertEquals(key, fixture.repository.originalSelections.loadOriginalSelection(origin, 8).getOrThrow()?.key)
            fixture.loseNextInsertAcknowledgement = true
            assertTrue(fixture.repository.submitOriginal(request).isFailure)
            val accepted = fixture.dao.allRows().single()
            assertEquals(null, fixture.repository.originalSelections.loadOriginalSelection(origin, 8).getOrThrow())
            fixture.reopen()
            assertEquals(accepted.id, fixture.repository.submitOriginal(request).getOrThrow())
            fixture.repository.collectOrphans()
            assertArrayEquals(image.bytes, fixture.fileStore.read(requireNotNull(draft.payload.file)))
            assertEquals(accepted, fixture.dao.allRows().single())
            assertEquals(0, fixture.apiCalls)
        }
    }

    @Test fun cancelledSelectionCannotPublishOrDiscardItsReplacementOrLeakAcrossBinding() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val session = fixture.session.value
            val origin = requireNotNull(fixture.repository.currentOriginalBinding())
            val payload = OriginalAttachmentPayload(operation = "attach_original", expenseId = 8, publicId = "expense-8",
                expectedRowVersion = 4, origin = origin)
            val first = OriginalSubmission(UUID.randomUUID().toString(), payload) { fixture.image("first.png") }
            val draft = fixture.repository.originalSelections.retainOriginalSelection(first).getOrThrow()
            fixture.repository.originalSelections.discardOriginalSelection(origin, first).getOrThrow()
            val replacement = fixture.repository.originalSelections.retainOriginalSelection(first.copy(key = UUID.randomUUID().toString())).getOrThrow()
            assertTrue(fixture.repository.submitOriginal(OriginalSubmission(draft.key, draft.payload, draft)).isFailure)
            assertTrue(fixture.dao.allRows().isEmpty())
            assertTrue(fixture.repository.originalSelections.discardOriginalSelection(origin, first).isFailure)
            assertEquals(replacement.key, fixture.repository.originalSelections.loadOriginalSelection(origin, 8).getOrThrow()?.key)
            fixture.session.value = session.copy(identity = session.identity.copy(role = "viewer"))
            assertTrue(fixture.repository.submitOriginal(OriginalSubmission(replacement.key, replacement.payload, replacement)).isFailure)
            fixture.session.value = session.copy(identity = session.identity.copy(ledgerId = "other"))
            assertTrue(fixture.repository.originalSelections.readOriginalSelection(replacement).isFailure)
            fixture.repository.collectOrphans()
            fixture.session.value = session
            assertTrue(fixture.repository.originalSelections.readOriginalSelection(replacement).isSuccess)
            fixture.repository.originalSelections.discardOriginalSelection(origin, OriginalSubmission(replacement.key, replacement.payload)).getOrThrow()
            fixture.repository.collectOrphans()
            assertFalse(fixture.original(replacement.key).exists())
        }
    }

    @Test fun capturedOriginalAdmitsAndRetriesOfflineWithoutReplacingItsKey() = runBlocking<Unit> {
        for (operation in listOf("attach_original", "replenish_original")) {
            UploadIntentRepositoryFixture().use { fixture ->
                val key = UUID.randomUUID().toString()
                val payload = OriginalAttachmentPayload(operation = operation, expenseId = 8, publicId = "expense-8",
                    expectedRowVersion = 4, origin = requireNotNull(fixture.repository.currentOriginalBinding()),
                    sha256 = if (operation == "attach_original") null else "a".repeat(64))
                var reads = 0
                val request = OriginalSubmission(key, payload) { reads++; fixture.image("captured-original.png") }
                val id = fixture.repository.submitOriginal(request).getOrThrow()
                val original = fixture.dao.allRows().single()
                fixture.reopen()
                assertEquals(id, fixture.repository.submitOriginal(request).getOrThrow())
                assertEquals(1, reads)
                fixture.outbox.markFailed(id, "original_connection_failed")
                fixture.repository.recoverOriginal(payload.origin, id, drop = false).getOrThrow()
                val retried = fixture.dao.allRows().single()
                assertEquals("pending", retried.status)
                assertEquals(key, retried.idempotencyKey)
                assertEquals(original.payload, retried.payload)
                assertEquals(original.expectedRowVersion, retried.expectedRowVersion)
                assertArrayEquals(fixture.image("captured-original.png").bytes,
                    fixture.fileStore.read(requireNotNull(readOriginalPayload(retried.toDomain())?.file)))
                assertEquals(0, fixture.apiCalls)
            }
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
