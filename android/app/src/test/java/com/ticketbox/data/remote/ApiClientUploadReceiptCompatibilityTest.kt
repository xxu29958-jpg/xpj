package com.ticketbox.data.remote

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import okio.ByteString
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@RunWith(Parameterized::class)
class ApiClientUploadReceiptCompatibilityTest(
    private val capabilityVersion: Int?,
    private val preVersioned: Boolean,
    private val keyed: Boolean,
    private val expectedUploadCount: Int,
    private val prefixed: Boolean,
) {
    private val uploadPath = if (prefixed) "/capture/api/app/upload-screenshot" else "/api/app/upload-screenshot"

    @Test
    fun keyedUploadRequiresConfirmedOriginalReceiptSupportBeforeSending() {
        val requests = mutableListOf<Request>()
        val uploadedBodies = mutableListOf<ByteString>()
        // Keep the real auth and negotiation interceptors; replace only HTTP transport.
        val client = buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                requests += request
                val responseBody = when (request.url.encodedPath) {
                    "/api/system/runtime-compatibility" -> runtimeJson()
                    uploadPath -> {
                        uploadedBodies += Buffer().also { checkNotNull(request.body).writeTo(it) }.readByteString()
                        "{}"
                    }
                    else -> error("Unexpected transport route")
                }
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
                    .code(200).message("Response")
                    .body(responseBody.toResponseBody("application/json".toMediaType())).build()
            }.build()
        val request = uploadRequest()
        val originalBody = Buffer().also { checkNotNull(request.body).writeTo(it) }.readByteString()

        client.newCall(request).execute().use { response ->
            val uploads = requests.filter { it.url.encodedPath == uploadPath }
            assertEquals(expectedUploadCount, uploads.size, "A capability refusal must send no upload HTTP request")
            assertEquals(expectedUploadCount, uploadedBodies.size)
            val negotiation = requests.single { it.url.encodedPath == "/api/system/runtime-compatibility" }
            assertEquals("GET", negotiation.method)
            assertEquals(request.url.host, negotiation.url.host)
            assertNull(negotiation.header("Idempotency-Key"))
            requests.forEach { sent ->
                assertEquals("Bearer test-session", sent.header("Authorization"))
                assertEquals("owner", sent.header(LEDGER_ID_HEADER))
            }
            if (expectedUploadCount == 0) {
                assertEquals(409, response.code)
                assertTrue(response.body.string().contains("runtime_version_mismatch"))
            } else {
                assertEquals(200, response.code)
                val upload = uploads.single()
                assertEquals("POST", upload.method)
                assertEquals(request.header("Idempotency-Key"), upload.header("Idempotency-Key"))
                assertEquals("Asia/Shanghai", upload.header("X-Timezone"))
                assertEquals(CURRENT_TICKETBOX_API_VERSION, upload.header(TICKETBOX_API_VERSION_HEADER))
                assertEquals("1:1:CNY", upload.header(TICKETBOX_CURRENCY_BINDING_HEADER))
                assertEquals(originalBody, uploadedBodies.single())
            }
        }
    }

    private fun runtimeJson(): String {
        val receiptCapability = capabilityVersion?.let { "\"upload_original_receipt_version\":$it," }.orEmpty()
        return """{
            "api_version":"$CURRENT_TICKETBOX_API_VERSION",
            "write_compatibility":"compatible",
            "capabilities":{$receiptCapability"currency":{"request_binding":"1:1:CNY"}}
        }""".trimIndent()
    }

    private fun uploadRequest(): Request {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "original.png", byteArrayOf(0, 1, 2, 3).toRequestBody("image/png".toMediaType()))
            .build()
        val builder = Request.Builder().url("https://example.test$uploadPath")
            .header("X-Timezone", "Asia/Shanghai").post(body)
        if (keyed) builder.header("Idempotency-Key", "original-upload-key")
        if (preVersioned) builder.header(TICKETBOX_API_VERSION_HEADER, CURRENT_TICKETBOX_API_VERSION)
        return builder.build()
    }

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "capability={0}, preVersioned={1}, keyed={2}, prefixed={4}")
        fun cases(): List<Array<Any?>> = listOf(
            arrayOf<Any?>(null, false, true, 0, false),
            arrayOf<Any?>(2, false, true, 0, false),
            arrayOf<Any?>(null, true, true, 0, false),
            arrayOf<Any?>(2, true, true, 0, true),
            arrayOf<Any?>(1, false, true, 1, false),
            arrayOf<Any?>(null, false, false, 1, false),
        )
    }
}
