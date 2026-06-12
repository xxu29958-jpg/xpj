package com.ticketbox.ui.navigation

import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.ticketbox.BuildConfig
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.UiText
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.resolve
import com.ticketbox.ui.screens.BindServerScreen
import com.ticketbox.ui.screens.LoginScreen
import com.ticketbox.ui.screens.ServerUrlEntryConfig
import com.ticketbox.ui.screens.settings.JoinFamilyLedgerScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.AppUiState
import com.ticketbox.viewmodel.AppViewModel
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel
import com.ticketbox.viewmodel.joinFamilyLedgerViewModelFactory

@Composable
fun TicketboxApp(
    repository: ExpenseRepository,
    ledgerRepository: LedgerRepository,
    recurringRepository: RecurringRepository,
    budgetRepository: BudgetRepository,
    reportsRepository: ReportsActions,
    incomePlanRepository: com.ticketbox.data.repository.IncomePlanActions,
    outboxRepository: OutboxRepository,
    tagRepository: com.ticketbox.data.repository.TagRepository,
    appViewModelFactory: ViewModelProvider.Factory,
    settingsViewModelFactory: ViewModelProvider.Factory,
    categoryRulesViewModelFactory: ViewModelProvider.Factory,
    merchantAliasViewModelFactory: ViewModelProvider.Factory,
    appearanceViewModelFactory: ViewModelProvider.Factory,
    biometricAuthManager: BiometricAuthManager,
    // 系统分享 / 启动器 shortcut 带进来的待处理请求；仅在 MainShell（已绑定+已解锁）
    // 内被消费。未绑定/未解锁时挂起等待，待门通过后由对应 LaunchedEffect 处理。
    launchRequest: LaunchIntentRequest? = null,
    onLaunchRequestHandled: () -> Unit = {},
) {
    val appViewModel: AppViewModel = viewModel(
        factory = appViewModelFactory,
    )
    val appState by appViewModel.uiState.collectAsStateWithLifecycle()
    val lifecycleOwner = LocalLifecycleOwner.current

    DisposableEffect(lifecycleOwner, appState.isBound) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_STOP -> appViewModel.markBackgrounded()
                Lifecycle.Event.ON_START -> appViewModel.refreshUnlockRequirement()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    TicketboxTheme(
        skin = appState.skin,
        currency = appState.currency,
        currencyDisplay = appState.currencyDisplay,
    ) {
        TicketboxContent(
            appState = appState,
            appViewModel = appViewModel,
            repository = repository,
            ledgerRepository = ledgerRepository,
            recurringRepository = recurringRepository,
            budgetRepository = budgetRepository,
            reportsRepository = reportsRepository,
            incomePlanRepository = incomePlanRepository,
            outboxRepository = outboxRepository,
            tagRepository = tagRepository,
            settingsViewModelFactory = settingsViewModelFactory,
            categoryRulesViewModelFactory = categoryRulesViewModelFactory,
            merchantAliasViewModelFactory = merchantAliasViewModelFactory,
            appearanceViewModelFactory = appearanceViewModelFactory,
            biometricAuthManager = biometricAuthManager,
            onAuthMessageShown = appViewModel::consumeAuthMessage,
            launchRequest = launchRequest,
            onLaunchRequestHandled = onLaunchRequestHandled,
        )
    }
}

@Composable
private fun TicketboxContent(
    appState: AppUiState,
    appViewModel: AppViewModel,
    repository: ExpenseRepository,
    ledgerRepository: LedgerRepository,
    recurringRepository: RecurringRepository,
    budgetRepository: BudgetRepository,
    reportsRepository: ReportsActions,
    incomePlanRepository: com.ticketbox.data.repository.IncomePlanActions,
    outboxRepository: OutboxRepository,
    tagRepository: com.ticketbox.data.repository.TagRepository,
    settingsViewModelFactory: ViewModelProvider.Factory,
    categoryRulesViewModelFactory: ViewModelProvider.Factory,
    merchantAliasViewModelFactory: ViewModelProvider.Factory,
    appearanceViewModelFactory: ViewModelProvider.Factory,
    biometricAuthManager: BiometricAuthManager,
    onAuthMessageShown: () -> Unit,
    launchRequest: LaunchIntentRequest?,
    onLaunchRequestHandled: () -> Unit,
) {
    if (!appState.isBound) {
        ImmersiveBackgroundScaffold(
            backgroundSettings = appState.backgroundSettings,
            currentSkin = appState.skin,
            surfaceRole = SurfaceRole.Auth,
        ) {
            UnboundAuthFlow(
                appState = appState,
                appViewModel = appViewModel,
                ledgerRepository = ledgerRepository,
            )
        }
        return
    }

    if (BuildConfig.REQUIRE_LOCAL_UNLOCK && !appState.unlocked) {
        ImmersiveBackgroundScaffold(
            backgroundSettings = appState.backgroundSettings,
            currentSkin = appState.skin,
            surfaceRole = SurfaceRole.Auth,
        ) {
            LoginScreen(
                message = appState.authMessage,
                onUnlock = { attemptBiometricUnlock(biometricAuthManager, appViewModel) },
            )
        }
        return
    }

    MainShell(
        repository = repository,
        ledgerRepository = ledgerRepository,
        recurringRepository = recurringRepository,
        budgetRepository = budgetRepository,
        reportsRepository = reportsRepository,
        incomePlanRepository = incomePlanRepository,
        outboxRepository = outboxRepository,
        tagRepository = tagRepository,
        settingsViewModelFactory = settingsViewModelFactory,
        categoryRulesViewModelFactory = categoryRulesViewModelFactory,
        merchantAliasViewModelFactory = merchantAliasViewModelFactory,
        appearanceViewModelFactory = appearanceViewModelFactory,
        currentSkin = appState.skin,
        currentCurrency = appState.currency,
        backgroundSettings = appState.backgroundSettings,
        startupMessage = appState.authMessage,
        onStartupMessageShown = onAuthMessageShown,
        onSkinChange = appViewModel::selectSkin,
        onCurrencyChange = appViewModel::selectCurrency,
        onBindingCleared = appViewModel::clearBinding,
        launchRequest = launchRequest,
        onLaunchRequestHandled = onLaunchRequestHandled,
    )
}

/**
 * Cold-start entry, two doors: pairing-code binding (configures this device
 * as the ledger owner's account) and「我有家庭邀请」— the invitation join for
 * family members, previously locked behind the already-bound settings tree
 * (the audit-P1 onboarding dead end). Join success persists the binding via
 * ``LedgerRepository.acceptInvitation`` and [AppViewModel.refreshBindingState]
 * flips the gate.
 */
@Composable
private fun UnboundAuthFlow(
    appState: AppUiState,
    appViewModel: AppViewModel,
    ledgerRepository: LedgerRepository,
) {
    var showJoinFlow by rememberSaveable { mutableStateOf(false) }
    val serverUrlEntry = ServerUrlEntryConfig(
        defaultUrl = BuildConfig.DEFAULT_SERVER_URL,
        showInput = BuildConfig.SHOW_ADVANCED_TOOLS || BuildConfig.DEFAULT_SERVER_URL.isBlank(),
    )
    if (showJoinFlow) {
        val joinViewModel: JoinFamilyLedgerViewModel = viewModel(
            key = "join-family-ledger-unbound",
            factory = joinFamilyLedgerViewModelFactory(ledgerRepository),
        )
        // The VM is activity-retained; wipe a previous attempt's state on
        // every (re-)entry so a stale success/error can't greet a new join.
        LaunchedEffect(joinViewModel) { joinViewModel.reset() }
        JoinFamilyLedgerScreen(
            viewModel = joinViewModel,
            onBack = { showJoinFlow = false },
            onAccepted = appViewModel::refreshBindingState,
            serverUrlEntry = serverUrlEntry,
        )
    } else {
        BindServerScreen(
            loading = appState.binding,
            message = appState.authMessage,
            serverUrlEntry = serverUrlEntry,
            onBind = appViewModel::bind,
            onJoinWithInvitation = { showJoinFlow = true },
        )
    }
}

@Composable
private fun MainShell(
    repository: ExpenseRepository,
    ledgerRepository: LedgerRepository,
    recurringRepository: RecurringRepository,
    budgetRepository: BudgetRepository,
    reportsRepository: ReportsActions,
    incomePlanRepository: com.ticketbox.data.repository.IncomePlanActions,
    outboxRepository: OutboxRepository,
    tagRepository: com.ticketbox.data.repository.TagRepository,
    settingsViewModelFactory: ViewModelProvider.Factory,
    categoryRulesViewModelFactory: ViewModelProvider.Factory,
    merchantAliasViewModelFactory: ViewModelProvider.Factory,
    appearanceViewModelFactory: ViewModelProvider.Factory,
    currentSkin: AppSkin,
    currentCurrency: com.ticketbox.domain.model.CurrencyCode,
    backgroundSettings: BackgroundSettings,
    startupMessage: UiText?,
    onStartupMessageShown: () -> Unit,
    onSkinChange: (AppSkin) -> Unit,
    onCurrencyChange: (com.ticketbox.domain.model.CurrencyCode) -> Unit,
    onBindingCleared: () -> Unit,
    launchRequest: LaunchIntentRequest?,
    onLaunchRequestHandled: () -> Unit,
) {
    val context = LocalContext.current
    val shellState = rememberMainShellState()
    val navController = rememberNavController()

    LaunchRequestEffect(launchRequest, shellState, onLaunchRequestHandled)

    val currentBackStackEntry by navController.currentBackStackEntryAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val screenFactory = remember(
        repository,
        ledgerRepository,
        recurringRepository,
        budgetRepository,
        reportsRepository,
        incomePlanRepository,
        outboxRepository,
        tagRepository,
        settingsViewModelFactory,
        categoryRulesViewModelFactory,
        merchantAliasViewModelFactory,
        appearanceViewModelFactory,
    ) {
        MainScreenFactory(
            repository = repository,
            ledgerRepository = ledgerRepository,
            recurringRepository = recurringRepository,
            budgetRepository = budgetRepository,
            reportsRepository = reportsRepository,
            incomePlanRepository = incomePlanRepository,
            outboxRepository = outboxRepository,
            tagRepository = tagRepository,
            settingsViewModelFactory = settingsViewModelFactory,
            categoryRulesViewModelFactory = categoryRulesViewModelFactory,
            merchantAliasViewModelFactory = merchantAliasViewModelFactory,
            appearanceViewModelFactory = appearanceViewModelFactory,
        )
    }

    LaunchedEffect(startupMessage) {
        val message = startupMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message.resolve(context))
        onStartupMessageShown()
    }

    ImmersiveBackgroundScaffold(
        backgroundSettings = backgroundSettings,
        currentSkin = currentSkin,
        surfaceRole = shellState.surfaceRole(currentBackStackEntry?.destination?.route),
    ) {
        MainNavGraph(
            navController = navController,
            shellState = shellState,
            screenFactory = screenFactory,
            currentSkin = currentSkin,
            currentCurrency = currentCurrency,
            snackbarHostState = snackbarHostState,
            onSkinChange = onSkinChange,
            onCurrencyChange = onCurrencyChange,
            onBindingCleared = onBindingCleared,
        )
    }
}

/**
 * 系统分享 / 启动器 shortcut 路由：只在 MainShell（已绑定+已解锁）里消费。把入口请求
 * 落成 tab 选择 + 一次性动作信号（拉起图片选择 / 待上传图 / 打开记一笔），由对应 Route
 * 接力；消费后回调清空 Activity 持有的请求（置回 null → 本 effect 以 null 重跑即 no-op）。
 */
@Composable
private fun LaunchRequestEffect(
    launchRequest: LaunchIntentRequest?,
    shellState: MainShellState,
    onLaunchRequestHandled: () -> Unit,
) {
    LaunchedEffect(launchRequest) {
        val request = launchRequest ?: return@LaunchedEffect
        dispatchLaunchRequest(request, shellState)
        onLaunchRequestHandled()
    }
}

/**
 * 把已解析的 [LaunchIntentRequest] 落到 [MainShellState] 的 tab 选择 + 一次性动作信号。
 * 抽成顶层非 composable 函数（而非内联进 LaunchedEffect）以压平嵌套——内联的
 * 双层 when 会触顶 detekt NestedBlockDepth；Navigate 再下沉一层保留单层 when。
 */
private fun attemptBiometricUnlock(
    biometricAuthManager: BiometricAuthManager,
    appViewModel: AppViewModel,
) {
    if (!biometricAuthManager.canAuthenticate()) {
        appViewModel.unlockFailed(UiText.res(R.string.app_unlock_no_biometric))
        return
    }
    biometricAuthManager.authenticate(
        onSuccess = appViewModel::unlockSucceeded,
        // BiometricAuthManager.onError 给的是已解析系统串,原样包装保持消息不变。
        onError = { message -> appViewModel.unlockFailed(UiText.raw(message)) },
    )
}

private fun dispatchLaunchRequest(request: LaunchIntentRequest, shellState: MainShellState) {
    when (request) {
        is LaunchIntentRequest.ShareImages -> {
            shellState.launchAction.post(LaunchAction.UploadSharedImages(request.uris))
            shellState.selectBottomTab(BottomTab.Pending.key)
        }
        is LaunchIntentRequest.Navigate -> dispatchShortcutNavigation(request.target, shellState)
    }
}

private fun dispatchShortcutNavigation(target: ShortcutTarget, shellState: MainShellState) {
    when (target) {
        ShortcutTarget.UploadReceipt -> {
            shellState.launchAction.post(LaunchAction.OpenImagePicker)
            shellState.selectBottomTab(BottomTab.Pending.key)
        }
        ShortcutTarget.ReviewPending ->
            shellState.selectBottomTab(BottomTab.Pending.key)
        ShortcutTarget.ManualEntry -> {
            shellState.launchAction.post(LaunchAction.OpenManualEntry)
            shellState.selectBottomTab(BottomTab.Ledger.key)
        }
    }
}
