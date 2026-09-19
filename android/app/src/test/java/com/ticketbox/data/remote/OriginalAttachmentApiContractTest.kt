package com.ticketbox.data.remote

import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.OriginalCleanupRequestDto
import com.ticketbox.data.remote.dto.OriginalCommandReceiptDto
import com.ticketbox.data.remote.dto.OriginalHealthDto
import com.ticketbox.data.remote.dto.OriginalVerificationRequestDto
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private const val DIGEST = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
private const val REQUEST_ID = "2518898d-ff04-4690-9caa-c7d8b8aba053"
private const val CHECKED_AT = "2026-09-20T10:00:00Z"

class OriginalAttachmentApiContractTest {
    private val moshi = Moshi.Builder().build()

    @Test fun healthRetainsCurrentIdentityAndIndependentPausedCleanup() {
        val json = """{"expense_id":7,"public_id":"bill-seven","row_version":12,"state":"verified",
            "checked_at":"$CHECKED_AT","expected_sha256":"$DIGEST","observed_sha256":"$DIGEST",
            "size_bytes":321,"media_type":"image/png","cleanup":{"request_id":"$REQUEST_ID",
            "reason":"after_confirm","requested_at":"2026-09-19T00:00:00Z","image":"deleted",
            "thumbnail":"pending","image_error":null,"thumbnail_error":"unlink_failed","policy_enabled":false}}
        """.trimIndent()
        val health = requireNotNull(moshi.adapter(OriginalHealthDto::class.java).fromJson(json))
        assertEquals(7L, health.expenseId)
        assertEquals(12L, health.rowVersion)
        assertEquals(DIGEST, health.expectedSha256)
        assertEquals(DIGEST, health.observedSha256)
        assertEquals(321L, health.sizeBytes)
        assertEquals("image/png", health.mediaType)
        assertEquals(CHECKED_AT, health.checkedAt)
        val cleanup = requireNotNull(health.cleanup)
        assertEquals(REQUEST_ID, cleanup.requestId)
        assertEquals("deleted", cleanup.image)
        assertEquals("pending", cleanup.thumbnail)
        assertEquals("unlink_failed", cleanup.thumbnailError)
        assertNull(cleanup.imageError)
        assertFalse(cleanup.policyEnabled)
    }

    @Test fun legacyOrDamagedCleanupDoesNotInventKnownIdentity() {
        val health = requireNotNull(moshi.adapter(OriginalHealthDto::class.java).fromJson(
            """{"expense_id":7,"public_id":"bill-seven","row_version":12,"state":"unverified",
                "checked_at":"$CHECKED_AT","observed_sha256":"$DIGEST",
                "cleanup_error":"attachment_cleanup_invalid"}""",
        ))
        assertNull(health.expectedSha256)
        assertNull(health.cleanup)
        assertEquals("attachment_cleanup_invalid", health.cleanupError)
        assertEquals("unverified", health.state)
    }

    @Test fun acceptedReceiptRoundTripsWithoutBecomingAHealthObservation() {
        val adapter = moshi.adapter(OriginalCommandReceiptDto::class.java)
        val receipt = requireNotNull(adapter.fromJson(receiptJson("retry_original_cleanup")))
        assertEquals("retry_original_cleanup", receipt.operation)
        assertEquals(REQUEST_ID, receipt.cleanupRequestId)
        assertEquals(false, receipt.cleanupPending)
        assertEquals(receipt, adapter.fromJson(adapter.toJson(receipt)))
        assertFalse(adapter.toJson(receipt).contains("\"state\""))
        assertFailsWith<JsonDataException> {
            moshi.adapter(OriginalHealthDto::class.java).fromJson(adapter.toJson(receipt))
        }
    }

    @Test fun commandBodiesKeepReviewedDigestRequestIdAndOriginalOcc() {
        val verification = moshi.adapter(OriginalVerificationRequestDto::class.java)
        assertEquals("""{"expected_row_version":11,"reviewed_sha256":"$DIGEST"}""",
            verification.toJson(OriginalVerificationRequestDto(11, DIGEST)))
        val cleanup = moshi.adapter(OriginalCleanupRequestDto::class.java)
        val body = OriginalCleanupRequestDto(11, REQUEST_ID)
        assertEquals("""{"expected_row_version":11,"request_id":"$REQUEST_ID"}""", cleanup.toJson(body))
        assertEquals(body, cleanup.fromJson(cleanup.toJson(body)))
    }

    @Test fun jsonEndpointsUseTheExistingBillAndPreserveTheCommandKey() = runBlocking {
        val observed = mutableListOf<Request>()
        val bodies = mutableListOf<String>()
        val api = api { request ->
            observed += request
            bodies += request.body?.let { Buffer().also(it::writeTo).readUtf8() }.orEmpty()
            when (request.url.encodedPath.substringAfterLast('/')) {
                "original" -> """{"expense_id":7,"public_id":"bill-seven","row_version":11,
                    "state":"missing","checked_at":"$CHECKED_AT","expected_sha256":"$DIGEST"}"""
                "verify" -> receiptJson("verify_original")
                "retry" -> receiptJson("retry_original_cleanup")
                else -> receiptJson("cancel_original_cleanup")
            }
        }
        assertEquals("missing", api.originalHealth(7).state)
        assertEquals("verify_original", api.verifyOriginal(7, OriginalVerificationRequestDto(11, DIGEST), "verify-key").operation)
        assertEquals("retry_original_cleanup", api.retryOriginalCleanup(7, OriginalCleanupRequestDto(11, REQUEST_ID), "retry-key").operation)
        assertEquals("cancel_original_cleanup", api.cancelOriginalCleanup(7, OriginalCleanupRequestDto(11, REQUEST_ID), "cancel-key").operation)
        assertEquals(listOf("GET", "POST", "POST", "POST"), observed.map { it.method })
        assertEquals(listOf("original", "original/verify", "original/cleanup/retry", "original/cleanup/cancel"),
            observed.map { it.url.encodedPath.removePrefix("/api/expenses/7/") })
        assertEquals(listOf(null, "verify-key", "retry-key", "cancel-key"), observed.map { it.header("Idempotency-Key") })
        assertTrue(bodies[1].contains("\"reviewed_sha256\":\"$DIGEST\""))
        bodies.drop(1).forEach { assertTrue(it.contains("\"expected_row_version\":11")) }
        bodies.drop(2).forEach { assertTrue(it.contains("\"request_id\":\"$REQUEST_ID\"")) }
    }

    @Test fun replenishmentKeepsRawBytesAndRequiredOccInQuery() = runBlocking {
        val original = byteArrayOf(0, 1, 2, 127, -128, -1)
        var observed: Request? = null
        val api = api { request ->
            observed = request
            val body = request.body as MultipartBody
            assertEquals(1, body.parts.size)
            val part = body.parts.single()
            assertEquals("form-data; name=\"file\"; filename=\"admitted.png\"", part.headers?.get("Content-Disposition"))
            assertContentEquals(original, Buffer().also(part.body::writeTo).readByteArray())
            receiptJson("replenish_original")
        }
        val part = MultipartBody.Part.createFormData("file", "admitted.png", original.toRequestBody("image/png".toMediaType()))
        val result = api.replenishOriginal(7, part, 11, DIGEST, "same-replenishment-key")
        assertEquals("replenish_original", result.operation)
        val request = requireNotNull(observed)
        assertEquals("POST", request.method)
        assertEquals("/api/expenses/7/original/replenish", request.url.encodedPath)
        assertEquals("11", request.url.queryParameter("expected_row_version"))
        assertEquals(DIGEST, request.url.queryParameter("expected_sha256"))
        assertEquals("same-replenishment-key", request.header("Idempotency-Key"))
    }

    private fun api(respond: (Request) -> String): ApiService {
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val request = chain.request()
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("Controlled response")
                .body(respond(request).toResponseBody("application/json".toMediaType())).build()
        }.build()
        return buildApiService("https://example.test/", client)
    }

    private fun receiptJson(operation: String): String =
        """{"operation":"$operation","expense_id":7,"public_id":"bill-seven","row_version":12,
            "sha256":"$DIGEST","accepted_at":"$CHECKED_AT","cleanup_request_id":"$REQUEST_ID","cleanup_pending":false}"""
}
