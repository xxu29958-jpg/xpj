package com.ticketbox.widget

import android.appwidget.AppWidgetHost
import android.appwidget.AppWidgetHostView
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.os.SystemClock
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.TicketboxApplication
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.StoredSessionToken
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

/** Actual AppWidgetService -> WorkManager -> Retrofit -> Room -> hosted RemoteViews. */
class WidgetWorkerJourneyTest {
    private val app = ApplicationProvider.getApplicationContext<TicketboxApplication>()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var host: AppWidgetHost
    private lateinit var view: AppWidgetHostView
    private var widgetId = 0

    @Test fun workerPublishesAndRecoversOfflineThenClearsThePreviousLedger() = runBlocking {
        val original = app.container.sessionStore.currentSession()
        val server = WidgetJourneyServer()
        try {
            val session = workerSession(server.url)
            app.container.sessionStore.establishSession(session)
            bindHost()
            awaitText(R.id.widget_amount, app.getString(R.string.widget_amount_hidden))
            WidgetPreferences(app).save(widgetId, session.version)
            WidgetUpdateWorker.enqueue(app)
            awaitText(R.id.widget_amount, "¥7,000")
            assertTrue(text(R.id.widget_title).contains("JPY"))
            val readTime = text(R.id.widget_updated).substringAfter("更新于 ")
            server.close()
            WidgetUpdateWorker.enqueue(app)
            awaitText(R.id.widget_updated, "离线快照 · $readTime")
            assertEquals("¥7,000", text(R.id.widget_amount))
            app.container.sessionStore.establishSession(session.copy(bindingRevision = UUID.randomUUID().toString(),
                identity = session.identity.copy(ledgerId = "new-widget-ledger", ledgerName = "另一个账本")))
            awaitText(R.id.widget_amount, app.getString(R.string.widget_amount_hidden))
            assertEquals(app.getString(R.string.widget_brand), text(R.id.widget_ledger))
            app.container.sessionStore.clearSession()
            awaitText(R.id.widget_amount, app.getString(R.string.widget_bind_first))
        } finally {
            server.close()
            WidgetPreferences(app).remove(intArrayOf(widgetId))
            instrumentation.runOnMainSync { if (::host.isInitialized) { host.stopListening(); host.deleteHost() } }
            instrumentation.uiAutomation.dropShellPermissionIdentity()
            if (original == null) app.container.sessionStore.clearSession() else app.container.sessionStore.establishSession(original)
        }
    }

    private fun bindHost() {
        instrumentation.uiAutomation.adoptShellPermissionIdentity("android.permission.BIND_APPWIDGET")
        val manager = AppWidgetManager.getInstance(app)
        instrumentation.runOnMainSync {
            host = AppWidgetHost(app, 884211)
            widgetId = host.allocateAppWidgetId()
            assertTrue(manager.bindAppWidgetIdIfAllowed(widgetId, ComponentName(app, MonthlyOverviewWidgetProvider::class.java)))
            view = host.createView(app, widgetId, manager.getAppWidgetInfo(widgetId))
            host.startListening()
            renderWidgetPlaceholders(app)
        }
    }

    private fun text(id: Int): String {
        var result = ""
        instrumentation.runOnMainSync { result = view.findViewById<TextView>(id)?.text?.toString().orEmpty() }
        return result
    }

    private fun awaitText(id: Int, expected: String) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (SystemClock.elapsedRealtime() < deadline && text(id) != expected) SystemClock.sleep(50)
        assertEquals(expected, text(id))
    }
}

private fun workerSession(url: String) = LocalSessionRecord(
    sessionGeneration = UUID.randomUUID().toString(), bindingRevision = UUID.randomUUID().toString(),
    serverId = UUID.randomUUID().toString(), dataGeneration = UUID.randomUUID().toString(),
    serverUrl = url, credential = StoredSessionToken("synthetic-widget-journey"),
    identity = LocalSessionIdentity(accountPublicId = UUID.randomUUID().toString(), devicePublicId = UUID.randomUUID().toString(),
        accountName = "测试成员", ledgerId = "widget-worker-ledger", ledgerName = "组件测试账本", deviceName = "模拟器",
        role = "member", boundAt = "2026-11-01T00:00:00Z"),
)
