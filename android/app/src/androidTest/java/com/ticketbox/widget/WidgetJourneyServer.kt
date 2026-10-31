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
    val trendReads = AtomicInteger()
    @Volatile var trendDelayMillis: Long = 0
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
            } catch (_: SocketException) {
                // Hiding a widget deliberately cancels its in-flight HTTP read.
                if (server.isClosed) break
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
        path.startsWith("/api/insights/data-quality") ->
            """{"pending_total":6,"missing_amount":1,"missing_merchant":0,"missing_category":0,"suspected_duplicates":0,"confirmed_without_image":0,"ready_to_confirm":5,"oldest_pending_age_days":2,"generated_at":"${java.time.Instant.now()}"}"""
        path.startsWith("/api/reports/overview") -> {
            trendReads.incrementAndGet()
            Thread.sleep(trendDelayMillis)
            trendResponse(requireNotNull(android.net.Uri.parse(path).getQueryParameter("month")))
        }
        else -> error("Unexpected widget request: ${path.substringBefore('?')}")
    }

    private fun trendResponse(value: String): String {
        val month = YearMonth.parse(value)
        val points = (1..month.lengthOfMonth()).joinToString(",") { day ->
            """{"bucket":"${month.atDay(day)}","label":"$day","amount_cents":100,"count":1}"""
        }
        return """{"month":"$month","timezone":"UTC","granularity":"day","total_amount_cents":3100,"count":31,"previous_month":"${month.minusMonths(1)}","previous_total_amount_cents":0,"previous_count":0,"year_over_year_month":"${month.minusYears(1)}","year_over_year_total_amount_cents":0,"year_over_year_count":0,"year_over_year_delta_amount_cents":3100,"year_over_year_delta_count":31,"merchant_category":null,"ranking_metric":"count","trend":[$points],"merchant_ranking":[],"category_comparison":[],"home_currency_code":"JPY","missing_rates":[],"undated_expense_count":0}"""
    }

    override fun close() {
        server.close()
        worker.join(1_000)
    }
}
