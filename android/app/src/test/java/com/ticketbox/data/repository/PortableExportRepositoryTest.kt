package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.buildApiHttpClient
import com.ticketbox.data.remote.buildApiService
import java.io.IOException
import java.io.OutputStream
import java.nio.file.Files
import java.util.Random
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import okio.ForwardingSource
import okio.Source
import okio.buffer
import okio.source
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class PortableExportRepositoryTest {
    @Test fun archivedSelectionStreamsReopenableZipThroughTheExistingIdentity() = runBlocking {
        val original = Files.createTempFile("portable-source", ".zip").toFile()
        val saved = Files.createTempFile("portable-saved", ".zip").toFile()
        try {
            ZipOutputStream(original.outputStream()).use { zip ->
                zip.putNextEntry(ZipEntry("manifest.json")); zip.write("{\"ledger_id\":\"archived\"}".toByteArray())
                zip.closeEntry(); zip.putNextEntry(ZipEntry("originals/receipt.bin"))
                val random = Random(42)
                val block = ByteArray(8192)
                repeat(256) { random.nextBytes(block); zip.write(block) }
                zip.closeEntry()
            }
            var opened = false
            var maximumWrite = 0
            val requests = mutableListOf<Request>()
            val fixture = PortableReadFixture { request ->
                requests += request
                if (request.url.encodedPath.endsWith("/ledgers")) {
                    reply(request, """{"ledgers":[{"ledger_id":"archived","name":"归档账本","role":"owner","is_default":false,"created_at":null,"archived_at":"2026-09-28T00:00:00Z"}]}"""
                        .toResponseBody("application/json".toMediaType()))
                } else {
                    reply(request, guardedBody(original.source(), original.length()) {
                        if (!opened) throw IOException("Retrofit buffered the ZIP before opening the destination")
                    })
                }
            }
            val binding = assertNotNull(fixture.repo.currentBinding())
            assertEquals("archived", fixture.repo.ledgers(binding).getOrThrow().single().ledgerId)
            val result = fixture.repo.download(PortableExportSelection(binding, "archived"), open = {
                opened = true
                val output = saved.outputStream()
                object : OutputStream() {
                    override fun write(value: Int) = error("Expected bounded block writes")
                    override fun write(bytes: ByteArray, offset: Int, count: Int) {
                        maximumWrite = maxOf(maximumWrite, count); output.write(bytes, offset, count)
                    }
                    override fun close() = output.close()
                }
            }, progress = {})
            assertEquals(original.length(), result.getOrThrow())
            assertTrue(maximumWrite in 1..65536)
            ZipFile(saved).use { zip ->
                assertEquals("{\"ledger_id\":\"archived\"}", zip.getInputStream(zip.getEntry("manifest.json")).reader().readText())
                assertEquals(2L * 1024 * 1024, zip.getEntry("originals/receipt.bin").size)
            }
            assertEquals("archived", requests.last().url.queryParameter("ledger_id"))
            assertTrue(requests.all { it.header("Authorization") == "Bearer portable-test-token" })
            assertEquals(binding, fixture.repo.currentBinding())
        } finally { original.delete(); saved.delete() }
    }

    @Test fun truncatedBodyCannotReportSavedAndAlwaysClosesTheDestination() = runBlocking {
        val output = CountingDestination()
        val fixture = PortableReadFixture { request -> reply(request, guardedBody(Buffer().write(ByteArray(64)), 128)) }
        val binding = assertNotNull(fixture.repo.currentBinding())
        val result = fixture.repo.download(PortableExportSelection(binding, "archived"), { output }, {})
        assertTrue(result.isFailure)
        assertEquals(64, output.count)
        assertTrue(output.closed)
        assertTrue(result.exceptionOrNull()?.message.orEmpty().contains("未完成"))
    }

    @Test fun replacingTheIdentityDuringCopyStopsBeforeAnotherChunk() = runBlocking {
        val fixture = PortableReadFixture { request -> reply(request, guardedBody(Buffer().write(ByteArray(160000)), 160000)) }
        val output = CountingDestination { fixture.session.clear() }
        val binding = assertNotNull(fixture.repo.currentBinding())
        val result = fixture.repo.download(PortableExportSelection(binding, "archived"), { output }, {})
        assertTrue(result.isFailure)
        assertTrue(output.count in 1..65536)
        assertTrue(output.closed)
    }

    @Test fun lostExportAuthorityDoesNotOpenAFileOrClearTheCredential() = runBlocking {
        val fixture = PortableReadFixture { request ->
            reply(request, """{"error":"ledger_forbidden","message":"无权下载这个账本。"}"""
                .toResponseBody("application/json".toMediaType()), 403)
        }
        val binding = assertNotNull(fixture.repo.currentBinding())
        var opened = false
        val result = fixture.repo.download(PortableExportSelection(binding, "archived"), {
            opened = true; CountingDestination()
        }, {})
        assertTrue(result.isFailure)
        assertFalse(opened)
        assertEquals(binding, fixture.repo.currentBinding())
    }
}

private class PortableReadFixture(response: (Request) -> Response) {
    val session = TestSessionFixture().apply { saveToken("portable-test-token") }
    private val factory = object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
            val client = buildApiHttpClient(null, tokenProvider, { "owner" }, null, null).newBuilder()
                .addInterceptor { response(it.request()) }.build()
            return buildApiService("$baseUrl/", client)
        }
    }
    val repo = PortableExportRepository(testApiServiceProvider(factory, session))
}

private class CountingDestination(private val afterWrite: () -> Unit = {}) : OutputStream() {
    var count = 0
    var closed = false
    override fun write(value: Int) { count++; afterWrite() }
    override fun write(bytes: ByteArray, offset: Int, length: Int) { count += length; afterWrite() }
    override fun close() { closed = true }
}

private fun guardedBody(source: Source, length: Long, beforeRead: () -> Unit = {}): ResponseBody =
    object : ResponseBody() {
        private val input = object : ForwardingSource(source) {
            override fun read(sink: Buffer, byteCount: Long): Long { beforeRead(); return super.read(sink, byteCount) }
        }.buffer()
        override fun contentType() = "application/zip".toMediaType()
        override fun contentLength() = length
        override fun source() = input
    }

private fun reply(request: Request, body: ResponseBody, code: Int = 200): Response = Response.Builder()
    .request(request).protocol(Protocol.HTTP_1_1).code(code).message("Export response").body(body).build()
