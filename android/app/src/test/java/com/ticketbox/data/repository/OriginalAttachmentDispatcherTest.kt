package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.OriginalCommandReceiptDto
import kotlinx.coroutines.test.runTest
import okhttp3.MultipartBody
import okio.Buffer
import okio.ByteString.Companion.toByteString
import org.junit.Test
import java.io.IOException
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

class OriginalAttachmentDispatcherTest {
    @Test fun lostAckReplaysSameBillBytesKeyAndOccWithoutCreatingPendingExpense() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val payload = payload()
        val key = requireNotNull(payload.file).key
        val json = originalPayloadAdapter.toJson(payload)
        val id = outbox.enqueue(PendingMutationType.OriginalAttachment, "expense:8", json, 4L, key)
        val sends = mutableListOf<String>()
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun replenishOriginal(id: Long, file: MultipartBody.Part, expectedRowVersion: Long,
                expectedSha256: String, idempotencyKey: String): OriginalCommandReceiptDto {
                assertEquals(8L, id)
                assertEquals(4L, expectedRowVersion)
                assertEquals(payload.sha256, expectedSha256)
                assertEquals("admitted original", Buffer().also { file.body.writeTo(it) }.readUtf8())
                sends += idempotencyKey
                if (sends.size == 1) throw IOException("accepted response lost")
                return receipt()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(OriginalAttachmentDispatcher({ api }) { "admitted original".encodeToByteArray() }))
        engine.drainOnce()
        assertNull(dao.rows.getValue(id).receiptJson)
        engine.drainOnce()
        assertEquals(listOf(key, key), sends)
        assertEquals(json, dao.rows.getValue(id).payload)
        assertEquals(4L, dao.rows.getValue(id).expectedRowVersion)
        assertEquals(receipt(), originalReceiptAdapter.fromJson(requireNotNull(dao.rows.getValue(id).receiptJson)))
        assertEquals(0, engine.drainOnce().attempted)
    }

    @Test fun anotherBillReceiptCannotSettleTheOriginalAndUnknownKindCannotSend() = runTest {
        val outbox = testOutboxRepository(FakePendingMutationDao())
        val payload = payload()
        outbox.enqueue(PendingMutationType.OriginalAttachment, "expense:8", originalPayloadAdapter.toJson(payload),
            4, payload.file!!.key)
        val row = outbox.activeForTarget("expense:8").single()
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun replenishOriginal(id: Long, file: MultipartBody.Part, expectedRowVersion: Long,
                expectedSha256: String, idempotencyKey: String) = receipt().copy(expenseId = 9)
        }
        val sender = OriginalAttachmentDispatcher({ api }) { "admitted original".encodeToByteArray() }
        assertEquals(DispatchResult.Failure("original_receipt_invalid"), sender.dispatch(row))
        assertIs<DispatchResult.Failure>(sender.dispatch(row.copy(payloadJson =
            originalPayloadAdapter.toJson(payload.copy(operation = "create_expense")))))
    }

    private fun payload(): OriginalAttachmentPayload {
        val binding = testOutboxBinding()
        val bytes = "admitted original".encodeToByteArray()
        val file = UploadIntentFileDescriptor("dddddddd-dddd-4ddd-8ddd-dddddddddddd", bytes.size.toLong(),
            bytes.toByteString().sha256().hex(), UploadIntentFileMetadata("original.png", "image/png", 0, bytes.size.toLong()))
        return OriginalAttachmentPayload(operation = "replenish_original", expenseId = 8, publicId = "expense-8",
            expectedRowVersion = 4, origin = LogicalSessionBinding(binding.serverUrl, binding.ledgerId,
                binding.ownerStorageKey, "session", "binding"), sha256 = file.sha256, file = file)
    }

    private fun receipt() = OriginalCommandReceiptDto("replenish_original", 8, "expense-8", 5,
        "2026-09-20T00:00:00Z", sha256 = payload().sha256)
}
