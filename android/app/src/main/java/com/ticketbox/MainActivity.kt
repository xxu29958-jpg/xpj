package com.ticketbox

import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.fragment.app.FragmentActivity
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.navigation.TicketboxApp
import com.ticketbox.viewmodel.appViewModelFactory
import com.ticketbox.viewmodel.settingsViewModelFactory

class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = (application as TicketboxApplication).container
        val biometricAuthManager = BiometricAuthManager(this)
        bindFromDebugIntentIfPresent(container)

        setContent {
            TicketboxApp(
                repository = container.expenseRepository,
                ledgerRepository = container.ledgerRepository,
                recurringRepository = container.recurringRepository,
                budgetRepository = container.budgetRepository,
                reportsRepository = container.reportsRepository,
                incomePlanRepository = container.incomePlanRepository,
                appViewModelFactory = appViewModelFactory(
                    repository = container.expenseRepository,
                    settingsStore = container.settingsStore,
                    tokenStore = container.tokenStore,
                ),
                settingsViewModelFactory = settingsViewModelFactory(
                    repository = container.expenseRepository,
                    ruleRepository = container.ruleRepository,
                    merchantRepository = container.merchantRepository,
                    settingsStore = container.settingsStore,
                ),
                biometricAuthManager = biometricAuthManager,
            )
        }
    }

    private fun bindFromDebugIntentIfPresent(container: AppContainer) {
        if (!BuildConfig.SHOW_ADVANCED_TOOLS) return
        if ((applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) == 0) return
        val serverUrl = intent.getStringExtra(DEBUG_SERVER_URL_EXTRA)?.trim()?.trimEnd('/')
        val sessionToken = intent.getStringExtra(DEBUG_SESSION_TOKEN_EXTRA)?.trim()
        if (serverUrl.isNullOrBlank() || sessionToken.isNullOrBlank()) return

        container.settingsStore.saveServerUrl(serverUrl)
        container.tokenStore.saveToken(sessionToken)
        container.settingsStore.markUnlocked()
    }

    private companion object {
        const val DEBUG_SERVER_URL_EXTRA = "ticketbox.debug.server_url"
        const val DEBUG_SESSION_TOKEN_EXTRA = "ticketbox.debug.session_token"
    }
}
