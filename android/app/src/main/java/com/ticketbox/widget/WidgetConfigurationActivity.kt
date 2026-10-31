package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.fragment.app.FragmentActivity
import com.ticketbox.BuildConfig
import com.ticketbox.MainActivity
import com.ticketbox.R
import com.ticketbox.TicketboxApplication
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.security.LocalSessionVersion
import com.ticketbox.security.LocalUnlockAvailability
import com.ticketbox.security.isBusinessReady

class WidgetConfigurationActivity : FragmentActivity() {
    private var widgetId = AppWidgetManager.INVALID_APPWIDGET_ID
    private val state = mutableStateOf(WidgetConfigurationState())
    private val container get() = (application as TicketboxApplication).container

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setResult(RESULT_CANCELED)
        widgetId = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        val info = AppWidgetManager.getInstance(this).getAppWidgetInfo(widgetId)
        if (info?.provider != ComponentName(this, MonthlyOverviewWidgetProvider::class.java)) {
            finish()
            return
        }
        setContent {
            WidgetConfigurationScreen(state.value, onSave = ::save, onOpenApp = {
                startActivity(Intent(this, MainActivity::class.java))
            }, onCancel = ::finish)
        }
    }

    override fun onResume() {
        super.onResume()
        val session = container.sessionStore.currentSession().takeIf { it.isBusinessReady() }
        state.value = WidgetConfigurationState(
            version = session?.version,
            ledgerName = session?.identity?.ledgerName,
            showSummary = WidgetPreferences(this).allowsSummary(widgetId, session?.version),
        )
    }

    private fun save(showSummary: Boolean) {
        val expected = state.value.version
        if (!showSummary) {
            complete(null)
            return
        }
        if (expected == null) return
        val auth = BiometricAuthManager(this)
        if (BuildConfig.REQUIRE_LOCAL_UNLOCK && auth.unlockAvailability() != LocalUnlockAvailability.None) {
            auth.authenticate(onSuccess = { complete(expected) }, onError = { state.value = state.value.copy(error = it) })
        } else {
            complete(expected)
        }
    }

    private fun complete(expected: LocalSessionVersion?) {
        if (expected != null && container.sessionStore.currentSession()?.version != expected) {
            state.value = state.value.copy(error = getString(R.string.widget_session_changed))
            return
        }
        WidgetPreferences(this).save(widgetId, expected)
        renderWidgetPlaceholders(this)
        WidgetUpdateWorker.enqueue(this)
        setResult(RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId))
        finish()
    }
}
