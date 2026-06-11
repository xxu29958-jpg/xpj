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
                onUnlock = {
                    if (!biometricAuthManager.canAuthenticate()) {
                        appViewModel.unlockFailed(UiText.res(R.string.app_unlock_no_biometric))
                        return@LoginScreen
                    }
                    biometricAuthManager.authenticate(
                        onSuccess = appViewModel::unlockSucceeded,
                        // BiometricAuthManager.onError hands an already-resolved
                        // system string; wrap verbatim so the message is unchanged.
                        onError = { message -> appViewModel.unlockFailed(UiText.raw(message)) },
                    )
                },
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
) {
    val context = LocalContext.current
    val shellState = rememberMainShellState()
    val navController = rememberNavController()
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
