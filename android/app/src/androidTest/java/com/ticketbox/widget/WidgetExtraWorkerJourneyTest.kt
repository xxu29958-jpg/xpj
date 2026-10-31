package com.ticketbox.widget

import android.appwidget.AppWidgetHost
import android.appwidget.AppWidgetHostView
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.os.SystemClock
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class WidgetExtraWorkerJourneyTest {
    private val app = ApplicationProvider.getApplicationContext<TicketboxApplication>()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val widgets = mutableMapOf<WidgetKind, Pair<Int, AppWidgetHostView>>()
    private lateinit var host: AppWidgetHost

    @Test fun tasksSyncTrendAndPrivacyUseTheirActualProvidersAndWorker() = runBlocking {
        val original = widgetOriginalSession(app)
        val server = WidgetJourneyServer()
        try {
            val session = workerSession(server.url)
            app.container.sessionStore.establishSession(session)
            bindWidgets()
            widgets.values.forEach { WidgetPreferences(app).save(it.first, session.version) }
            WidgetUpdateWorker.enqueue(app)
            await(WidgetKind.Tasks, R.id.widget_first_count, "6")
            await(WidgetKind.Sync, R.id.widget_first_count, "0")
            await(WidgetKind.Trend, R.id.widget_status, "近 7 天净支出 · JPY")
            assertTrue(text(WidgetKind.Trend, R.id.widget_comparison).contains("比上周同期 ¥0"))
            server.trendDelayMillis = 500
            val reads = server.trendReads.get()
            WidgetUpdateWorker.enqueue(app)
            waitUntil { server.trendReads.get() > reads }
            app.sendBroadcast(Intent(app, SpendingTrendWidgetProvider::class.java).setAction(DataWidgetProvider.ACTION_HIDE)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgets.getValue(WidgetKind.Trend).first))
            await(WidgetKind.Trend, R.id.widget_status, app.getString(R.string.widget_data_hidden))
            SystemClock.sleep(800)
            assertEquals(app.getString(R.string.widget_data_hidden), text(WidgetKind.Trend, R.id.widget_status))
            assertFalse(WidgetPreferences(app).allowsSummary(widgets.getValue(WidgetKind.Trend).first, session.version))
            server.close()
            WidgetUpdateWorker.enqueue(app)
            await(WidgetKind.Tasks, R.id.widget_first_count, "—")
            await(WidgetKind.Sync, R.id.widget_second_count, "0")
            app.container.sessionStore.clearSession()
            widgets.keys.forEach { await(it, R.id.widget_status, app.getString(R.string.widget_bind_first)) }
        } finally {
            server.close()
            WidgetPreferences(app).remove(widgets.values.map { it.first }.toIntArray())
            instrumentation.runOnMainSync { if (::host.isInitialized) { host.stopListening(); host.deleteHost() } }
            instrumentation.uiAutomation.dropShellPermissionIdentity()
            if (original == null) app.container.sessionStore.clearSession() else app.container.sessionStore.establishSession(original)
        }
    }

    private fun bindWidgets() {
        instrumentation.uiAutomation.adoptShellPermissionIdentity("android.permission.BIND_APPWIDGET")
        val manager = AppWidgetManager.getInstance(app)
        instrumentation.runOnMainSync {
            host = AppWidgetHost(app, 884212)
            listOf(WidgetKind.Tasks, WidgetKind.Sync, WidgetKind.Trend).forEach { kind ->
                val id = host.allocateAppWidgetId()
                assertTrue(manager.bindAppWidgetIdIfAllowed(id, ComponentName(app, kind.provider)))
                widgets[kind] = id to host.createView(app, id, manager.getAppWidgetInfo(id))
            }
            host.startListening()
            renderWidgetPlaceholders(app)
        }
    }

    private fun text(kind: WidgetKind, id: Int): String {
        var result = ""
        instrumentation.runOnMainSync { result = widgets.getValue(kind).second.findViewById<TextView>(id).text.toString() }
        return result
    }

    private fun await(kind: WidgetKind, id: Int, expected: String) {
        waitUntil { text(kind, id) == expected }
        assertEquals(expected, text(kind, id))
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (!condition() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50)
        assertTrue(condition())
    }
}
