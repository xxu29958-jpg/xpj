package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.fragment.app.FragmentActivity
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
    private var credentialVersion: String? = null
    private var revealAttempted = false
    private val credentialLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val current = container.sessionStore.currentSession()?.version
        if (result.resultCode == RESULT_OK && current != null && current.toString() == credentialVersion) complete(current)
        else restoreSummarySelection(getString(R.string.widget_verification_not_completed))
        credentialVersion = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setResult(RESULT_CANCELED)
        widgetId = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        credentialVersion = savedInstanceState?.getString("credentialVersion")
        revealAttempted = savedInstanceState?.getBoolean("revealAttempted") ?: false
        val info = AppWidgetManager.getInstance(this).getAppWidgetInfo(widgetId)
        if (WidgetKind.entries.none { info?.provider == ComponentName(this, it.provider) }) {
            finish()
            return
        }
        setContent {
            WidgetConfigurationScreen(state.value, onSave = ::save, onOpenApp = {
                startActivity(Intent(this, MainActivity::class.java))
            }, onCancel = ::finish, onSecuritySettings = {
                startActivity(Intent(Settings.ACTION_SECURITY_SETTINGS))
            })
        }
    }

    override fun onResume() {
        super.onResume()
        val session = container.sessionStore.currentSession().takeIf { it.isBusinessReady() }
        state.value = WidgetConfigurationState(
            version = session?.version,
            ledgerName = session?.identity?.ledgerName.takeIf { WidgetPreferences(this).allowsSummary(widgetId, session?.version) },
            showSummary = WidgetPreferences(this).allowsSummary(widgetId, session?.version),
            canAuthenticate = BiometricAuthManager(this).unlockAvailability() != LocalUnlockAvailability.None ||
                getSystemService(KeyguardManager::class.java).isDeviceSecure,
        )
        if (intent.getBooleanExtra(EXTRA_REVEAL, false) && !revealAttempted && session != null) {
            revealAttempted = true
            state.value = state.value.copy(showSummary = true)
            save(true)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("credentialVersion", credentialVersion)
        outState.putBoolean("revealAttempted", revealAttempted)
        super.onSaveInstanceState(outState)
    }

    private fun save(showSummary: Boolean) {
        state.value = state.value.copy(error = null)
        val expected = state.value.version
        if (!showSummary) {
            complete(null)
            return
        }
        if (expected == null) return
        val auth = BiometricAuthManager(this)
        if (auth.unlockAvailability() != LocalUnlockAvailability.None) {
            auth.authenticate(onSuccess = { complete(expected) }, onError = ::restoreSummarySelection)
        } else {
            // Device credentials on Android 9/10 use the system confirmation activity.
            @Suppress("DEPRECATION")
            val confirmation = getSystemService(KeyguardManager::class.java)
                .createConfirmDeviceCredentialIntent(getString(R.string.widget_reveal), null)
            if (confirmation == null) state.value = state.value.copy(error = getString(R.string.widget_lock_required))
            else {
                credentialVersion = expected.toString()
                credentialLauncher.launch(confirmation)
            }
        }
    }

    private fun restoreSummarySelection(message: String) {
        state.value = state.value.copy(
            showSummary = WidgetPreferences(this).allowsSummary(widgetId, container.sessionStore.currentSession()?.version),
            error = message,
        )
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

    companion object { internal const val EXTRA_REVEAL = "com.ticketbox.widget.REVEAL" }
}
