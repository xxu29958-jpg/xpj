package com.ticketbox.widget

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.repository.CorrectionConnectedNetwork
import java.net.ServerSocket
import java.net.SocketException
import java.time.YearMonth
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import kotlinx.coroutines.runBlocking

/** Local HTTP transport only; the app's production repositories and scheduler remain intact. */
internal class WidgetJourneyServer : AutoCloseable {
    private val server = ServerSocket(0)
    val url = "http://127.0.0.1:${server.localPort}"
    val monthlyReads = AtomicInteger()
    private val runtime = runBlocking {
        val dto = CorrectionConnectedNetwork().service.runtimeCompatibility().let {
            it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = 1))
        }
        Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(RuntimeCompatibilityDto::class.java).toJson(dto)
    }
    private val worker = thread(name = "widget-fixture-http") {
        while (!server.isClosed) {
            try {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader()
                    val path = reader.readLine()?.split(' ')?.getOrNull(1).orEmpty()
                    while (!reader.readLine().isNullOrEmpty()) { /* headers */ }
                    val body = response(path).toByteArray(Charsets.UTF_8)
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(body)
                        flush()
                    }
                }
            } catch (error: SocketException) {
                if (!server.isClosed) throw error
            }
        }
    }

    private fun response(path: String): String = when {
        path.startsWith("/api/system/runtime-compatibility") -> runtime
        path.startsWith("/api/ledgers/widget-worker-ledger/calendar") ->
            """{"ledger_id":"widget-worker-ledger","revision":1,"timezone_name":"UTC","basis":"explicit","adopted_at":"2026-01-01T00:00:00Z"}"""
        path.startsWith("/api/stats/monthly") -> {
            monthlyReads.incrementAndGet()
            """{"home_currency_code":"JPY","month":"${YearMonth.now(ZoneOffset.UTC)}","total_amount_cents":7000,"count":2,"by_category":[]}"""
        }
        else -> error("Unexpected widget request: ${path.substringBefore('?')}")
    }

    override fun close() {
        server.close()
        worker.join(1_000)
    }
}
