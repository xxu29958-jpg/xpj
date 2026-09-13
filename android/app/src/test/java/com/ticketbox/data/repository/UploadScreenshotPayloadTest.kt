package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class UploadScreenshotPayloadTest {
    private val adapter = OutboxAdapterGraph().uploadPayloadAdapter

    @Test
    fun originalBatchFileAndCompleteBindingSurviveRealJsonRoundTrip() {
        val payload = originalPayload()
        val row = originalRow(payload)
        assertEquals(payload, adapter.readSupportedUpload(row))
        assertEquals(payload, adapter.fromJson(adapter.toJson(payload)))
        assertEquals(payload.file?.key, row.idempotencyKey)
    }

    @Test
    fun changedIdentityOrOrderCannotBecomeAnotherCommand() {
        val payload = originalPayload()
        val row = originalRow(payload)
        assertNull(adapter.readSupportedUpload(row.copy(idempotencyKey = uploadItemKey(payload.batch.id, 1))))
        assertNull(adapter.readSupportedUpload(row.copy(targetId = "upload_batch:other")))
        assertNull(adapter.readSupportedUpload(row.copy(ownerKey = "another-owner")))
        assertNull(adapter.readSupportedUpload(row.copy(ledgerId = "another-ledger")))
        assertNull(adapter.readSupportedUpload(row.copy(expectedRowVersion = 1L)))
        assertNull(adapter.readSupportedUpload(originalRow(payload.copy(batch = payload.batch.copy(index = 3)))))
    }

    @Test
    fun unreadableSlotStillHasAnOriginalIdentityButNoInventedFile() {
        val payload = originalPayload().copy(file = null)
        assertEquals(payload, assertNotNull(adapter.readSupportedUpload(originalRow(payload))))
    }

    @Test
    fun unknownOrIncompletePayloadCannotReplay() {
        val payload = originalPayload()
        assertNull(adapter.readSupportedUpload(originalRow(payload.copy(revision = 2))))
        assertNull(adapter.readSupportedUpload(originalRow(payload.copy(timezone = ""))))
        assertNull(adapter.readSupportedUpload(originalRow(payload.copy(origin = payload.origin.copy(bindingRevision = "")))))
        assertNull(adapter.readSupportedUpload(originalRow(payload).copy(payloadJson = "{}")))
        assertNull(adapter.readSupportedUpload(originalRow(payload).copy(payloadJson = "null")))
    }

    private fun originalPayload(): UploadScreenshotPayload {
        val id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        return UploadScreenshotPayload(
            revision = 1,
            batch = UploadBatchPosition(id, 0, 3, id),
            origin = LogicalSessionBinding("https://api.example.com", "owner", "original-owner", "session", "binding"),
            timezone = "Asia/Shanghai",
            file = UploadIntentFileDescriptor(uploadItemKey(id, 0), 4L, "a".repeat(64),
                UploadIntentFileMetadata("original.png", "image/png", 3L, 4L)),
        )
    }

    private fun originalRow(payload: UploadScreenshotPayload) = OutboxRow(
        id = 1L, serverUrl = payload.origin.serverUrl, ledgerId = payload.origin.ledgerId,
        ownerKey = payload.origin.ownerKey, type = PendingMutationType.UploadScreenshot,
        targetId = "upload_batch:${payload.batch.groupId}", payloadJson = adapter.toJson(payload),
        expectedRowVersion = 0L, status = PendingMutationStatus.Pending, retryCount = 0,
        lastError = null, createdAt = "2026-09-07T00:00:00.000Z", attemptedAt = null, completedAt = null,
        idempotencyKey = uploadItemKey(payload.batch.id, payload.batch.index),
    )
}
