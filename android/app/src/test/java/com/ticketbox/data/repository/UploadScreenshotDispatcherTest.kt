package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.UploadResponseDto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import okio.ByteString.Companion.toByteString
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class UploadScreenshotDispatcherTest {
    private val adapters = OutboxAdapterGraph()

    @Test
    fun originalKeyTimezoneAndFileReachOnlySenderAndCompleteReceiptIsPersisted() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val payload = originalPayload()
        val id = outbox.enqueue(PendingMutationType.UploadScreenshot, "upload_batch:${payload.batch.groupId}",
            adapters.uploadPayloadAdapter.toJson(payload), 0L, payload.file!!.key)
        var sends = 0
        val api = uploadApi { file, timezone, key ->
            sends++
            assertEquals(payload.file.key, key)
            assertEquals("Asia/Shanghai", timezone)
            assertTrue(file.headers.toString().contains("original.png"))
            assertEquals("image/png", file.body.contentType().toString())
            assertEquals("original", Buffer().also { file.body.writeTo(it) }.readUtf8())
            receipt()
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher(api)))
        var adviceChanges = 0
        engine.onAdviceInputReplaySucceeded = { adviceChanges++ }
        assertEquals(1, engine.drainOnce().done)
        val original = dao.rows.getValue(id)
        assertEquals(PendingMutationStatus.Done.wireValue, original.status)
        assertEquals(receipt(), adapters.uploadReceiptAdapter.fromJson(requireNotNull(original.receiptJson)))
        assertEquals(adapters.uploadReceiptAdapter.toJson(receipt()), original.receiptJson)
        assertEquals(adapters.uploadPayloadAdapter.toJson(payload), original.payload)
        assertEquals(payload.file.key, original.idempotencyKey)
        assertEquals(0L, original.expectedRowVersion)
        assertEquals(0, engine.drainOnce().attempted)
        assertEquals(1, sends)
        assertEquals(0, adviceChanges)
    }

    @Test
    fun capacityAndProtocolRefusalsKeepTheOriginalCommandWithoutASuccessExit() = runTest {
        for ((status, code) in listOf(503 to "enrichment_capacity_full", 409 to "runtime_version_mismatch",
            409 to "client_upgrade_required")) {
            val failure = dispatcher(uploadApi { _, _, _ -> throw refusal(status, code) }).dispatch(originalRow())
            assertEquals(DispatchResult.Failure(code), failure)
        }
        val missingEndpoint = dispatcher(uploadApi { _, _, _ -> throw refusal(404, "not_found") }).dispatch(originalRow())
        assertFalse(assertIs<DispatchResult.Failure>(missingEndpoint).blocksFollowing)
    }

    @Test
    fun rejectedOriginalsKeepTheirReasonAndCannotRepeatTheSameRequest() = runTest {
        for ((status, code) in listOf(400 to "unsupported_file_type", 413 to "file_too_large", 422 to "invalid_request")) {
            val dao = FakePendingMutationDao()
            val outbox = testOutboxRepository(dao)
            val payload = originalPayload()
            val id = outbox.enqueue(PendingMutationType.UploadScreenshot, "upload_batch:${payload.batch.groupId}",
                adapters.uploadPayloadAdapter.toJson(payload), 0L, payload.file!!.key)
            var sends = 0
            val engine = OutboxDrainEngine(outbox, listOf(dispatcher(uploadApi { _, _, _ ->
                sends++
                throw refusal(status, code)
            })))
            assertEquals(1, engine.drainOnce().failures)
            val rejected = dao.rows.getValue(id)
            assertEquals(code, rejected.lastError)
            assertFalse(rejected.blocksFollowing)
            assertFalse(PendingUploadIntent(originalRow().copy(status = PendingMutationStatus.Failed,
                lastError = rejected.lastError), payload, null).canRetry)
            assertFalse(outbox.resolveFailed(id, FailedResolution.Retry()))
            assertEquals(0, engine.drainOnce().attempted)
            assertEquals(1, sends)
            assertEquals(rejected, dao.rows.getValue(id))
            assertNull(rejected.receiptJson)
        }
    }

    @Test
    fun unreadableAndUnsupportedOriginalsDoNotReadOrSend() = runTest {
        var reads = 0
        val dispatch = UploadScreenshotDispatcher({ error("must not bind HTTP") }, adapters.uploadPayloadAdapter,
            adapters.uploadReceiptAdapter, { reads++; error("must not read a file") })
        val row = originalRow()
        assertEquals(DispatchResult.Failure(UPLOAD_UNREADABLE, blocksFollowing = false),
            dispatch.dispatch(row.copy(payloadJson = adapters.uploadPayloadAdapter.toJson(originalPayload().copy(file = null)))))
        assertEquals(DispatchResult.Failure(UPLOAD_UNSUPPORTED), dispatch.dispatch(row.copy(idempotencyKey = "other")))
        assertEquals(0, reads)
    }

    @Test
    fun cancellationCannotBeConvertedIntoUploadFailureOrDelivery() = runTest {
        val cancellation = CancellationException("cancel original upload")
        val failure = assertFailsWith<CancellationException> {
            dispatcher(uploadApi { _, _, _ -> throw cancellation }).dispatch(originalRow())
        }
        assertEquals(cancellation, failure)
        assertNull(originalRow().receiptJson)
    }

    private fun dispatcher(api: ApiService) = UploadScreenshotDispatcher({ api }, adapters.uploadPayloadAdapter,
        adapters.uploadReceiptAdapter, { "original".encodeToByteArray() })

    private fun originalPayload(): UploadScreenshotPayload {
        val id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        val binding = testOutboxBinding()
        return UploadScreenshotPayload(1, UploadBatchPosition(id, 0, 1, id),
            LogicalSessionBinding(binding.serverUrl, binding.ledgerId, binding.ownerStorageKey, "session", "binding"),
            "Asia/Shanghai", UploadIntentFileDescriptor(uploadItemKey(id, 0), 8L,
                "original".encodeToByteArray().toByteString().sha256().hex(),
                UploadIntentFileMetadata("original.png", "image/png", 1L, 8L)))
    }

    private fun originalRow(): OutboxRow {
        val payload = originalPayload()
        return OutboxRow(1L, payload.origin.serverUrl, payload.origin.ledgerId, payload.origin.ownerKey,
            PendingMutationType.UploadScreenshot, "upload_batch:${payload.batch.groupId}",
            adapters.uploadPayloadAdapter.toJson(payload), 0L, PendingMutationStatus.Pending, 0, null,
            "2026-09-07T00:00:00.000Z", null, null, payload.file!!.key)
    }

    private fun receipt() = UploadResponseDto(1L, "expense-1", "task-1", "pending", "accepted", "b".repeat(64),
        null, "suspected", 7L, 8L, 3L, mapOf("save" to 2L))

    private fun refusal(status: Int, code: String) = HttpException(Response.error<UploadResponseDto>(status,
        """{"error":"$code","message":"refused"}""".toResponseBody("application/json".toMediaType())))

    private fun uploadApi(send: suspend (MultipartBody.Part, String?, String?) -> UploadResponseDto): ApiService =
        object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?, idempotencyKey: String?) =
                send(file, timezone, idempotencyKey)
        }
}
