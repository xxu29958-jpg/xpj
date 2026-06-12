package com.ticketbox

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.core.content.IntentCompat
import androidx.fragment.app.FragmentActivity
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.navigation.EXTRA_SHORTCUT_TARGET
import com.ticketbox.ui.navigation.LaunchIntentRequest
import com.ticketbox.ui.navigation.TicketboxApp
import com.ticketbox.ui.navigation.resolveLaunchIntent
import kotlinx.coroutines.runBlocking
import com.ticketbox.viewmodel.appViewModelFactory
import com.ticketbox.viewmodel.appearanceViewModelFactory
import com.ticketbox.viewmodel.categoryRulesViewModelFactory
import com.ticketbox.viewmodel.merchantAliasViewModelFactory
import com.ticketbox.viewmodel.settingsViewModelFactory

class MainActivity : FragmentActivity() {
    // 系统分享 / 启动器 shortcut 带进来的待处理请求。Activity 是 singleTask，
    // 在前台时新分享走 onNewIntent，更新此 state；MainShell 的 LaunchedEffect
    // 消费后置回 null。冷启动则由 onCreate 用 getIntent() 填充。
    // 纯内存持有(不进 savedInstanceState):分享到达时若未绑定/锁屏,请求挂着等
    // 过门;期间进程被杀则请求丢失——分享动作用户可重发,语义可接受。
    private val launchRequest = mutableStateOf<LaunchIntentRequest?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = (application as TicketboxApplication).container
        val biometricAuthManager = BiometricAuthManager(this)
        bindFromDebugIntentIfPresent(container)
        launchRequest.value = parseLaunchIntent(intent)

        setContent {
            TicketboxApp(
                launchRequest = launchRequest.value,
                onLaunchRequestHandled = { launchRequest.value = null },
                repository = container.expenseRepository,
                ledgerRepository = container.ledgerRepository,
                recurringRepository = container.recurringRepository,
                budgetRepository = container.budgetRepository,
                reportsRepository = container.reportsRepository,
                incomePlanRepository = container.incomePlanRepository,
                outboxRepository = container.outboxRepository,
                tagRepository = container.tagRepository,
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

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // singleTask: 前台时的分享/快捷方式都从这里来。更新 Activity 的 intent 以保持
        // getIntent() 一致，再喂给 state；为 null（普通 re-launch）则不覆盖已有待处理请求。
        setIntent(intent)
        parseLaunchIntent(intent)?.let { launchRequest.value = it }
    }

    /**
     * Activity 边界胶水：从 framework Intent 抽出纯 JVM 输入，交给可测的
     * [resolveLaunchIntent] 裁决。EXTRA_STREAM（单/多）+ clipData 都读，clipData
     * 是部分来源（如直接拖拽）唯一带 uri 的位置。
     */
    private fun parseLaunchIntent(intent: Intent?): LaunchIntentRequest? {
        intent ?: return null
        return resolveLaunchIntent(
            action = intent.action,
            mimeType = intent.type,
            streamUris = collectStreamUris(intent),
            shortcutTarget = intent.getStringExtra(EXTRA_SHORTCUT_TARGET),
        )
    }

    /** EXTRA_STREAM（单 Uri + Uri 列表）与 clipData 三处汇总成 uri 字符串。 */
    private fun collectStreamUris(intent: Intent): List<String> = buildList {
        IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
            ?.let { add(it.toString()) }
        IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
            ?.forEach { add(it.toString()) }
        addAll(clipDataUris(intent))
    }

    private fun clipDataUris(intent: Intent): List<String> {
        val clip = intent.clipData ?: return emptyList()
        return (0 until clip.itemCount).mapNotNull { clip.getItemAt(it)?.uri?.toString() }
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
