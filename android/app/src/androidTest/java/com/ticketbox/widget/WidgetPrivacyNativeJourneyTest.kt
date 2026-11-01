package com.ticketbox.widget

import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.appwidget.AppWidgetHost
import android.appwidget.AppWidgetHostView
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.TicketboxApplication
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

/** QA prepares an isolated device PIN and widget-bind grant, then drives the actual system credential UI. */
class WidgetPrivacyNativeJourneyTest {
    private val app = ApplicationProvider.getApplicationContext<TicketboxApplication>()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var host: AppWidgetHost
    private lateinit var view: AppWidgetHostView
    private var widgetId = 0
    private val resumed = AtomicInteger()
    private val configuration = AtomicReference<Activity?>()
    private val lifecycle = object : Application.ActivityLifecycleCallbacks {
        override fun onActivityCreated(activity: Activity, state: Bundle?) {
            if (activity is WidgetConfigurationActivity) configuration.set(activity)
        }
        override fun onActivityResumed(activity: Activity) { if (activity is WidgetConfigurationActivity) resumed.incrementAndGet() }
        override fun onActivityStarted(activity: Activity) = Unit
        override fun onActivityPaused(activity: Activity) = Unit
        override fun onActivityStopped(activity: Activity) = Unit
        override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
        override fun onActivityDestroyed(activity: Activity) = Unit
    }

    @Test fun cancelDoesNotRevealCorrectCredentialRevealsAndHideNeedsNoPrompt() = runBlocking {
        assertTrue("The isolated QA device needs a temporary screen lock", app.getSystemService(KeyguardManager::class.java).isDeviceSecure)
        val original = widgetOriginalSession(app)
        val server = WidgetJourneyServer()
        app.registerActivityLifecycleCallbacks(lifecycle)
        try {
            val session = workerSession(server.url)
            app.container.sessionStore.establishSession(session)
            bindWidget()
            val preferences = WidgetPreferences(app)
            launchConfiguration()
            phase("cancel_reveal")
            waitUntil { resumed.get() >= 2 }
            assertFalse(preferences.allowsSummary(widgetId, session.version))
            instrumentation.runOnMainSync { configuration.get()?.finish() }
            launchConfiguration()
            phase("enter_device_pin")
            waitUntil { preferences.allowsSummary(widgetId, session.version) }
            waitUntil { amount() == "¥7,000" }
            app.sendBroadcast(Intent(app, MonthlyOverviewWidgetProvider::class.java).setAction(DataWidgetProvider.ACTION_HIDE)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId))
            waitUntil { !preferences.allowsSummary(widgetId, session.version) }
            waitUntil { amount() == app.getString(R.string.widget_amount_hidden) }
            phase("verified_reveal_and_immediate_hide")
        } finally {
            server.close()
            WidgetPreferences(app).remove(intArrayOf(widgetId))
            instrumentation.runOnMainSync {
                configuration.get()?.finish()
                if (::host.isInitialized) { host.stopListening(); host.deleteHost() }
            }
            app.unregisterActivityLifecycleCallbacks(lifecycle)
            if (original == null) app.container.sessionStore.clearSession() else app.container.sessionStore.establishSession(original)
        }
    }

    private fun bindWidget() {
        val manager = AppWidgetManager.getInstance(app)
        instrumentation.runOnMainSync {
            host = AppWidgetHost(app, 884213)
            widgetId = host.allocateAppWidgetId()
            assertTrue(manager.bindAppWidgetIdIfAllowed(widgetId, ComponentName(app, MonthlyOverviewWidgetProvider::class.java)))
            view = host.createView(app, widgetId, manager.getAppWidgetInfo(widgetId))
            host.startListening()
            renderWidgetPlaceholders(app)
        }
    }

    private fun launchConfiguration() {
        app.startActivity(Intent(app, WidgetConfigurationActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId).putExtra(WidgetConfigurationActivity.EXTRA_REVEAL, true))
    }

    private fun amount(): String {
        var result = ""
        instrumentation.runOnMainSync { result = view.findViewById<TextView>(R.id.widget_amount)?.text?.toString().orEmpty() }
        return result
    }
    private fun phase(value: String) = instrumentation.sendStatus(0, Bundle().apply { putString("privacy_phase", value) })
    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 120_000
        while (!condition() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50)
        assertTrue(condition())
    }
}
