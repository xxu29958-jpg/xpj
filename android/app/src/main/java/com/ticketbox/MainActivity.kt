package com.ticketbox

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.core.content.IntentCompat
import androidx.core.view.doOnPreDraw
import androidx.fragment.app.FragmentActivity
import com.ticketbox.data.local.BackgroundImageStore
import com.ticketbox.data.repository.LocalBackgroundImageRepository
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.navigation.EXTRA_SHORTCUT_TARGET
import com.ticketbox.ui.navigation.LaunchIntentRequest
import com.ticketbox.ui.navigation.LaunchSharedContent
import com.ticketbox.ui.navigation.MainFeatureRepositories
import com.ticketbox.ui.navigation.MainScreenViewModelFactories
import com.ticketbox.ui.navigation.TicketboxApp
import com.ticketbox.ui.navigation.TicketboxAppDependencies
import com.ticketbox.ui.navigation.TicketboxAppViewModelFactories
import com.ticketbox.ui.navigation.resolveLaunchIntent
import com.ticketbox.ui.navigation.mergeLaunchRequest
import com.ticketbox.ui.navigation.remainingLaunchRequest
import com.ticketbox.ui.navigation.restoreLaunchRequest
import com.ticketbox.ui.navigation.savedFields
import java.util.UUID
import kotlinx.coroutines.runBlocking
import com.ticketbox.viewmodel.appViewModelFactory
import com.ticketbox.viewmodel.appearanceViewModelFactory
import com.ticketbox.viewmodel.categoryRulesViewModelFactory
import com.ticketbox.viewmodel.merchantAliasViewModelFactory
import com.ticketbox.viewmodel.settingsViewModelFactory

class MainActivity : FragmentActivity() {
    // URI references stay here until their original files and Room batch are durably accepted.
    // Each hot share remains a separate selection; saved state preserves its id and frozen binding.
    private val launchRequests = mutableStateOf<List<LaunchIntentRequest>>(emptyList())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = (application as TicketboxApplication).container
        val biometricAuthManager = BiometricAuthManager(this)
        bindFromDebugIntentIfPresent(container)
        val appDependencies = container.ticketboxAppDependencies(biometricAuthManager)
        launchRequests.value = if (savedInstanceState?.containsKey(SAVED_REQUEST_COUNT) == true) {
            val restored = List(savedInstanceState.getInt(SAVED_REQUEST_COUNT)) { index ->
                restoreLaunchRequest(requireNotNull(savedInstanceState.getStringArrayList("$SAVED_REQUEST_COUNT.$index")))
            }
            // Invitation text retains its existing OS-intent lifetime; do not add it to saved navigation state.
            val invitation = parseLaunchIntent(intent) as? LaunchIntentRequest.JoinInvitation
            listOfNotNull(invitation) + restored
        } else listOfNotNull(parseLaunchIntent(intent))

        setContent {
            TicketboxApp(
                dependencies = appDependencies,
                launchRequest = launchRequests.value.firstOrNull(),
                onLaunchRequestHandled = ::clearHandledLaunchIntent,
            )
        }
        window.decorView.doOnPreDraw {
            (application as TicketboxApplication).scheduleStartupWorkersAfterLaunchSettles()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // singleTask: 前台时的分享/快捷方式都从这里来。更新 Activity 的 intent 以保持
        // getIntent() 一致，再喂给 state；为 null（普通 re-launch）则不覆盖已有待处理请求。
        intent.removeExtra(UPLOAD_BATCH_ID)
        intent.removeExtra(LAUNCH_HANDLED)
        setIntent(intent)
        parseLaunchIntent(intent)?.let { launchRequests.value = mergeLaunchRequest(launchRequests.value, it) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        val requests = launchRequests.value.filterNot { it is LaunchIntentRequest.JoinInvitation }
        outState.putInt(SAVED_REQUEST_COUNT, requests.size)
        requests.forEachIndexed { index, request ->
            outState.putStringArrayList("$SAVED_REQUEST_COUNT.$index", request.savedFields())
        }
        super.onSaveInstanceState(outState)
    }

    /**
     * Activity 边界胶水：从 framework Intent 抽出纯 JVM 输入，交给可测的
     * [resolveLaunchIntent] 裁决。EXTRA_STREAM（单/多）+ clipData 都读，clipData
     * 是部分来源（如直接拖拽）唯一带 uri 的位置。
     */
    private fun parseLaunchIntent(intent: Intent?): LaunchIntentRequest? {
        intent ?: return null
        if (intent.getBooleanExtra(LAUNCH_HANDLED, false)) return null
        val batchId = intent.getStringExtra(UPLOAD_BATCH_ID) ?: UUID.randomUUID().toString()
        val request = resolveLaunchIntent(
            action = intent.action,
            mimeType = intent.type,
            shared = LaunchSharedContent(
                uris = collectStreamUris(intent),
                text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString() ?: firstClipText(intent),
                batchId = batchId,
            ),
            shortcutTarget = intent.getStringExtra(EXTRA_SHORTCUT_TARGET),
        )
        if (request is LaunchIntentRequest.ShareImages) intent.putExtra(UPLOAD_BATCH_ID, request.batchId)
        return request
    }

    /** Clear a handled request while preserving shares arriving during its handoff. */
    private fun clearHandledLaunchIntent(handled: LaunchIntentRequest) {
        launchRequests.value = remainingLaunchRequest(launchRequests.value, handled)
        if (parseLaunchIntent(intent) == handled) intent.putExtra(LAUNCH_HANDLED, true)
    }

    /** EXTRA_STREAM（单 Uri + Uri 列表）与 clipData 三处汇总成 uri 字符串。 */
    private fun collectStreamUris(intent: Intent): List<String> = buildList {
        IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
            ?.let { add(it.toString()) }
        IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
            ?.forEach { add(it.toString()) }
        addAll(clipDataUris(intent))
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
            container.replaceCredentialsForDebug(serverUrl, sessionToken)
        }
    }

    private fun AppContainer.ticketboxAppDependencies(
        biometricAuthManager: BiometricAuthManager,
    ): TicketboxAppDependencies = TicketboxAppDependencies(
        repositories = mainFeatureRepositories(),
        viewModelFactories = ticketboxAppViewModelFactories(),
        biometricAuthManager = biometricAuthManager,
    )

    private fun AppContainer.mainFeatureRepositories(): MainFeatureRepositories = MainFeatureRepositories(
        uploadIntents = uploadIntentRepository,
        repository = expenseRepository,
        ledgerRepository = ledgerRepository,
        recurringRepository = recurringRepository,
        budgetRepository = budgetRepository,
        reportsRepository = reportsRepository,
        incomePlanRepository = incomePlanRepository,
        debtRepository = debtRepository,
        debtCreationRepository = debtCreationRepository,
        debtAdjustmentRepository = debtAdjustmentRepository,
        repaymentDraftRepository = repaymentDraftRepository,
        outboxRepository = outboxRepository,
        tagRepository = tagRepository,
        categoryPreferenceRepository = categoryPreferenceRepository,
    )

    private fun AppContainer.ticketboxAppViewModelFactories(): TicketboxAppViewModelFactories =
        TicketboxAppViewModelFactories(
            appViewModelFactory = appViewModelFactory(
                repository = expenseRepository,
                settingsStore = settingsStore,
            ),
            mainScreenFactories = MainScreenViewModelFactories(
                settingsViewModelFactory = settingsViewModelFactory(
                    repository = expenseRepository,
                    settingsStore = settingsStore,
                ),
                categoryRulesViewModelFactory = categoryRulesViewModelFactory(
                    ruleRepository = ruleRepository,
                    repository = expenseRepository,
                ),
                merchantAliasViewModelFactory = merchantAliasViewModelFactory(
                    merchantRepository = merchantRepository,
                    repository = expenseRepository,
                ),
                appearanceViewModelFactory = appearanceViewModelFactory(
                    settingsStore = settingsStore,
                    images = LocalBackgroundImageRepository(BackgroundImageStore(applicationContext)),
                ),
            ),
        )

    private companion object {
        const val SAVED_REQUEST_COUNT = "ticketbox.launch.pending.count"
        const val UPLOAD_BATCH_ID = "ticketbox.launch.upload.batch_id"
        const val LAUNCH_HANDLED = "ticketbox.launch.handled"
        const val DEBUG_SERVER_URL_EXTRA = "ticketbox.debug.server_url"
        const val DEBUG_SESSION_TOKEN_EXTRA = "ticketbox.debug.session_token"
    }
}

/** Read-only Intent extraction; neither helper owns Activity state or consumes a request. */
private fun firstClipText(intent: Intent): String? {
    val clip = intent.clipData ?: return null
    return (0 until clip.itemCount)
        .firstNotNullOfOrNull { index -> clip.getItemAt(index)?.text?.toString() }
}

private fun clipDataUris(intent: Intent): List<String> {
    val clip = intent.clipData ?: return emptyList()
    return (0 until clip.itemCount).mapNotNull { clip.getItemAt(it)?.uri?.toString() }
}
