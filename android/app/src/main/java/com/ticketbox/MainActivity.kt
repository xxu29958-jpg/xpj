package com.ticketbox

import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.fragment.app.FragmentActivity
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.navigation.TicketboxApp
import kotlinx.coroutines.runBlocking
import com.ticketbox.viewmodel.appViewModelFactory
import com.ticketbox.viewmodel.appearanceViewModelFactory
import com.ticketbox.viewmodel.categoryRulesViewModelFactory
import com.ticketbox.viewmodel.merchantAliasViewModelFactory
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
                    settingsStore = container.settingsStore,
                ),
                categoryRulesViewModelFactory = categoryRulesViewModelFactory(
                    ruleRepository = container.ruleRepository,
                    repository = container.expenseRepository,
                ),
                merchantAliasViewModelFactory = merchantAliasViewModelFactory(
                    merchantRepository = container.merchantRepository,
                    repository = container.expenseRepository,
                ),
                appearanceViewModelFactory = appearanceViewModelFactory(
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

        // ADR-0038 PR-2g.3 codex round-12 P1: this debug-bind path
        // bypasses [LocalLedgerSessionCoordinator.applyTransition]
        // (which is the canonical session-change boundary that
        // clears the outbox in round-8 + round-10 + round-11). Any
        // queued mutation from a previous debug-bind would
        // otherwise replay against whatever serverUrl/token the
        // dev just stuffed into the intent extras — wrong-session
        // replay on the same numeric expense id space.
        //
        // ``runBlocking`` is acceptable here: this code path only
        // runs in internal debug builds with FLAG_DEBUGGABLE, on
        // an explicit ``am start --es ticketbox.debug.*`` invocation
        // — never on a user device. Blocking the main thread for a
        // single DELETE FROM pending_mutations + epoch bump +
        // OutboxScheduler.cancel/ensurePeriodic is well under the
        // ANR threshold and keeps the sync contract that
        // ``setContent`` below assumes (bound credentials by the
        // time UI inflates).
        runBlocking {
            container.outboxRepository.withBindingTransition(clearExistingRows = true) {
                container.settingsStore.saveServerUrl(serverUrl)
                container.tokenStore.saveToken(sessionToken)
                container.settingsStore.markUnlocked()
            }
        }
    }

    private companion object {
        const val DEBUG_SERVER_URL_EXTRA = "ticketbox.debug.server_url"
        const val DEBUG_SESSION_TOKEN_EXTRA = "ticketbox.debug.session_token"
    }
}
