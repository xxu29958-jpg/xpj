package com.ticketbox.data.repository

import com.ticketbox.BuildConfig
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody
import okio.Buffer
import okio.BufferedSource
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.shadows.ShadowLog
import retrofit2.HttpException
import java.io.IOException
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
class NetworkErrorReportingTest {
    private val handler = NetworkErrorHandler({ "https://example.test" }, "ReportingProbe")

    @Before
    fun clearLog() = ShadowLog.clear()

    @Test
    fun realDecodeCarriesBodyIdConflictAndCauseToFinalLogWithOneBodyRead() = runTest {
        val body = CountingBody("""{"error":"tag_conflict","request_id":"body-id","message":"private financial text",
            "conflict_tag_public_id":"tag-id","conflict_tag_row_version":7}""")
        val original = httpError(body, "header-id", 409)
        val failure = handler.safeCall<Unit> { throw original }.exceptionOrNull() as RepositoryException
        assertEquals("body-id", failure.requestId)
        assertEquals("tag_conflict", failure.errorCode)
        assertEquals(7L, failure.conflictTagRowVersion)
        assertEquals(409, failure.httpStatusCode)
        assertSame(original, failure.cause)
        assertEquals(1, body.reads)
        val output = finalLog()
        assertTrue(output.contains("request_id=body-id"))
        assertTrue(output.contains("request_id_mismatch=true header_request_id=header-id"))
        assertTrue(output.contains("code=tag_conflict"))
        assertFalse(output.contains("private financial text"))
        assertLocated(output)
    }

    @Test
    fun oldMalformedAndHeaderOnlyResponsesKeepFallbackAndNeverInventServerIds() {
        for (body in listOf("""{"error":"server_error"}""", "invalid JSON")) {
            val withHeader = handler.httpFailure(httpError(CountingBody(body), "header-only"))
            assertEquals("header-only", withHeader.requestId)
            assertTrue(finalLog().contains("request_id=header-only"))
        }
        val old = handler.httpFailure(httpError(CountingBody("""{"error":"server_error"}""")))
        assertEquals("server_error", old.errorCode)
        assertNull(old.requestId)
        assertTrue(finalLog().contains("request_id=absent"))
    }

    @Test
    fun transportAndUnexpectedErrorsKeepResultsAndCausesWithoutPrintingSecrets() = runTest {
        val secrets = listOf("synthetic-bearer", "synthetic-upload", "87654321", "synthetic-password")
        val root = IOException("Authorization: Bearer ${secrets[0]} password=${secrets[3]}")
        val failure = IllegalStateException("https://host.test/u/${secrets[1]}#pairing=${secrets[2]}", root)
        for (original in listOf(root, failure)) {
            val result = handler.safeCall<Unit> { throw original }
            val reported = result.exceptionOrNull() as RepositoryException
            assertOriginalCause(original, reported.cause)
            assertNull(reported.requestId)
        }
        logNetworkWarning("Authorization: Bearer ${secrets[0]} url=https://host.test/u/${secrets[1]} " +
            "pairing=${secrets[2]} password=${secrets[3]}", failure)
        val output = finalLog()
        assertTrue(output.contains("IOException") && output.contains("IllegalStateException"))
        assertTrue(secrets.none(output::contains))
        assertLocated(output)
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun cancellationAndExistingBusinessFailureKeepOriginalObjects() = runTest {
        val cancellation = CancellationException("cancel probe")
        try {
            handler.safeCall<Unit> { throw cancellation }
            error("cancellation was swallowed")
        } catch (actual: CancellationException) {
            assertOriginalCause(cancellation, actual)
        }
        val refusal = RepositoryException("existing business refusal")
        assertSame(refusal, handler.safeCall<Unit> { throw refusal }.exceptionOrNull())
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").isEmpty())
    }

    @Test
    @Config(shadows = [FailedLogSink::class])
    fun failedLogSinkDoesNotReplaceTheOriginalNetworkFailureOrRetryIt() = runTest {
        val original = IOException("synthetic failure")
        var attempts = 0
        val result = handler.safeCall<Unit> { attempts += 1; throw original }
        assertEquals(1, attempts)
        assertOriginalCause(original, result.exceptionOrNull()?.cause)
    }

    private fun assertLocated(output: String) {
        assertTrue(output.contains("operation=ReportingProbe"))
        assertTrue(output.contains("source_tree_sha256=${BuildConfig.SOURCE_FINGERPRINT}"))
        assertTrue(BuildConfig.SOURCE_FINGERPRINT.matches(Regex("[a-f0-9]{64}")))
        assertTrue(output.contains("NetworkErrorReportingTest.kt:"))
        assertTrue(output.contains("reported_at:"))
    }

    private fun assertOriginalCause(original: Throwable, actual: Throwable?) {
        // Coroutine stacktrace recovery may copy an exception across withContext,
        // retaining the original in its cause chain. That existing behavior stays intact.
        assertTrue(generateSequence(actual) { it.cause }.take(16).any { it === original })
    }

    private fun finalLog(): String = ShadowLog.getLogsForTag("TicketboxNetwork")
        .joinToString("\n") { assertNotNull(it.msg) }

    private class CountingBody(private val text: String) : ResponseBody() {
        var reads = 0
        override fun contentType() = "application/json".toMediaTypeOrNull()
        override fun contentLength() = text.toByteArray().size.toLong()
        override fun source(): BufferedSource {
            reads += 1
            return Buffer().writeUtf8(text)
        }
    }

    private fun httpError(body: ResponseBody, requestId: String? = null, status: Int = 503): HttpException {
        val raw = Response.Builder().protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://example.test/u/synthetic-upload").build())
            .code(status).message("test").apply { if (requestId != null) header("X-Request-ID", requestId) }.build()
        return HttpException(retrofit2.Response.error<Unit>(body, raw))
    }
}

@Implements(Log::class)
class FailedLogSink {
    companion object {
        @JvmStatic
        @Implementation
        fun w(tag: String?, message: String?): Int {
            if (tag == "TicketboxNetwork") error("synthetic log output failure")
            return 0
        }
    }
}
