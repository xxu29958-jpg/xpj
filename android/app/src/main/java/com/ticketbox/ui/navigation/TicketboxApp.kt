package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.components.AppBottomNav
import com.ticketbox.ui.components.AppBottomNavItem
import com.ticketbox.ui.screens.BindServerScreen
import com.ticketbox.ui.screens.ExpenseEditScreen
import com.ticketbox.ui.screens.LedgerScreen
import com.ticketbox.ui.screens.LoginScreen
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.screens.RecurringScreen
import com.ticketbox.ui.screens.SettingsScreen
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.upload.prepareScreenshotUpload
import com.ticketbox.viewmodel.AppUiState
import com.ticketbox.viewmodel.AppViewModel
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.LedgerViewModel
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.SettingsViewModel
import com.ticketbox.viewmodel.StatsViewModel
import com.ticketbox.viewmodel.closeSheet
import com.ticketbox.viewmodel.confirmReadyExpenses
import com.ticketbox.viewmodel.expenseEditViewModelFactory
import com.ticketbox.viewmodel.openBulkConfirm
import com.ticketbox.viewmodel.openDuplicateAction
import com.ticketbox.viewmodel.openMissingAmount
import com.ticketbox.viewmodel.openQuickCategory
import com.ticketbox.viewmodel.openQuickMerchant
import com.ticketbox.viewmodel.repositoryViewModelFactory
import com.ticketbox.viewmodel.recurringViewModelFactory
import com.ticketbox.viewmodel.saveAmountAndConfirm
import com.ticketbox.viewmodel.saveAmountDraft
import com.ticketbox.viewmodel.saveQuickCategory
import com.ticketbox.viewmodel.saveQuickMerchant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private enum class BottomTab(
    val key: String,
    val label: String,
    val icon: ImageVector,
) {
    Pending("pending", "待确认", Icons.Default.CheckCircle),
    Ledger("ledger", "账本", Icons.AutoMirrored.Filled.ReceiptLong),
    Stats("stats", "统计", Icons.Default.BarChart),
    Recurring("recurring", "固定", Icons.Filled.Category),
    Settings("settings", "设置", Icons.Default.Settings),
}

@Composable
fun TicketboxApp(
    repository: ExpenseRepository,
    ledgerRepository: LedgerRepository,
    recurringRepository: RecurringRepository,
    appViewModelFactory: ViewModelProvider.Factory,
    settingsViewModelFactory: ViewModelProvider.Factory,
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

    TicketboxTheme(skin = appState.skin) {
        TicketboxContent(
            appState = appState,
            appViewModel = appViewModel,
            repository = repository,
            ledgerRepository = ledgerRepository,
            recurringRepository = recurringRepository,
            settingsViewModelFactory = settingsViewModelFactory,
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
    settingsViewModelFactory: ViewModelProvider.Factory,
    biometricAuthManager: BiometricAuthManager,
    onAuthMessageShown: () -> Unit,
) {
    if (!appState.isBound) {
        ImmersiveBackgroundScaffold(
            backgroundSettings = appState.backgroundSettings,
            currentSkin = appState.skin,
            surfaceRole = SurfaceRole.Auth,
        ) {
            BindServerScreen(
                loading = appState.binding,
                message = appState.authMessage,
                defaultServerUrl = BuildConfig.DEFAULT_SERVER_URL,
                showServerUrlInput = BuildConfig.SHOW_ADVANCED_TOOLS || BuildConfig.DEFAULT_SERVER_URL.isBlank(),
                onBind = appViewModel::bind,
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
                        appViewModel.unlockFailed("请先在系统中设置指纹、面容或锁屏密码。")
                        return@LoginScreen
                    }
                    biometricAuthManager.authenticate(
                        onSuccess = appViewModel::unlockSucceeded,
                        onError = appViewModel::unlockFailed,
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
        settingsViewModelFactory = settingsViewModelFactory,
        currentSkin = appState.skin,
        backgroundSettings = appState.backgroundSettings,
        startupMessage = appState.authMessage,
        onStartupMessageShown = onAuthMessageShown,
        onSkinChange = appViewModel::selectSkin,
        onBindingCleared = {
            appViewModel.clearBinding()
        },
    )
}

@Composable
private fun MainShell(
    repository: ExpenseRepository,
    ledgerRepository: LedgerRepository,
    recurringRepository: RecurringRepository,
    settingsViewModelFactory: ViewModelProvider.Factory,
    currentSkin: AppSkin,
    backgroundSettings: BackgroundSettings,
    startupMessage: String?,
    onStartupMessageShown: () -> Unit,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    var selectedTab by remember { mutableStateOf(BottomTab.Pending) }
    var editingExpense by remember { mutableStateOf<Expense?>(null) }
    val repositoryFactory = repositoryViewModelFactory(repository)
    val currentRole = editingExpense?.let { SurfaceRole.Edit } ?: selectedTab.surfaceRole
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(startupMessage) {
        val message = startupMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        onStartupMessageShown()
    }

    ImmersiveBackgroundScaffold(
        backgroundSettings = backgroundSettings,
        currentSkin = currentSkin,
        surfaceRole = currentRole,
    ) {
        editingExpense?.let { expense ->
            val editViewModel: ExpenseEditViewModel = viewModel(
                key = "expense-edit-${expense.id}",
                factory = expenseEditViewModelFactory(expense.id, repository),
            )
            val editState by editViewModel.uiState.collectAsStateWithLifecycle()
            ExpenseEditScreen(
                expense = expense,
                state = editState,
                onSave = editViewModel::save,
                onConfirm = editViewModel::confirm,
                onReject = editViewModel::reject,
                onRetryOcr = editViewModel::retryOcr,
                onLoadFullImage = editViewModel::loadFullImage,
                onKeepDuplicate = editViewModel::markNotDuplicate,
                onDone = { editingExpense = null },
                allowConfirm = expense.status == "pending",
                allowReject = expense.status == "pending",
            )
            return@ImmersiveBackgroundScaffold
        }

        Scaffold(
            containerColor = Color.Transparent,
            contentWindowInsets = WindowInsets(0.dp),
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                AppBottomNav(
                    items = BottomTab.entries.map { it.toBottomNavItem() },
                    selectedKey = selectedTab.key,
                    onSelect = { item ->
                        BottomTab.entries.firstOrNull { it.key == item.key }?.let { selectedTab = it }
                    },
                )
            },
        ) { innerPadding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .consumeWindowInsets(innerPadding),
            ) {
                when (selectedTab) {
                BottomTab.Pending -> {
                    val pendingViewModel: PendingViewModel = viewModel(factory = repositoryFactory)
                    val state by pendingViewModel.uiState.collectAsStateWithLifecycle()
                    val context = LocalContext.current
                    val uploadScope = rememberCoroutineScope()
                    val imagePickerLauncher = rememberLauncherForActivityResult(
                        contract = ActivityResultContracts.PickVisualMedia(),
                    ) { uri ->
                        if (uri == null) return@rememberLauncherForActivityResult
                        if (!pendingViewModel.markUploadPreparing()) return@rememberLauncherForActivityResult
                        uploadScope.launch {
                            val selected = withContext(Dispatchers.IO) {
                                context.prepareScreenshotUpload(uri)
                            }
                            if (selected == null) {
                                pendingViewModel.uploadPreparationFailed()
                                return@launch
                            }
                            pendingViewModel.uploadScreenshot(
                                fileName = selected.fileName,
                                contentType = selected.contentType,
                                bytes = selected.bytes,
                                preparationDurationMs = selected.preparationDurationMs,
                                sourceSizeBytes = selected.sourceSizeBytes,
                                uploadAlreadyStarted = true,
                            )
                        }
                    }
                    PendingScreen(
                        state = state,
                        onRefresh = pendingViewModel::refresh,
                        onEdit = { editingExpense = it },
                        onConfirm = pendingViewModel::confirm,
                        onReject = pendingViewModel::reject,
                        onKeepDuplicate = pendingViewModel::markNotDuplicate,
                        onUploadScreenshot = {
                            imagePickerLauncher.launch(
                                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
                            )
                        },
                        onQuickCategory = pendingViewModel::openQuickCategory,
                        onSaveQuickCategory = pendingViewModel::saveQuickCategory,
                        onQuickMerchant = pendingViewModel::openQuickMerchant,
                        onSaveQuickMerchant = pendingViewModel::saveQuickMerchant,
                        onMissingAmount = pendingViewModel::openMissingAmount,
                        onSaveAmountDraft = pendingViewModel::saveAmountDraft,
                        onSaveAmountAndConfirm = pendingViewModel::saveAmountAndConfirm,
                        onOpenBulkConfirm = pendingViewModel::openBulkConfirm,
                        onConfirmReady = pendingViewModel::confirmReadyExpenses,
                        onOpenDuplicate = pendingViewModel::openDuplicateAction,
                        onIgnoreDuplicate = pendingViewModel::reject,
                        onCloseSheet = pendingViewModel::closeSheet,
                    )
                }
                BottomTab.Ledger -> {
                    val ledgerViewModel: LedgerViewModel = viewModel(factory = repositoryFactory)
                    val state by ledgerViewModel.uiState.collectAsStateWithLifecycle()
                    val context = LocalContext.current
                    var pendingExport by remember { mutableStateOf<CsvExport?>(null) }
                    val exportLauncher = rememberLauncherForActivityResult(
                        contract = ActivityResultContracts.CreateDocument("text/csv"),
                    ) { uri ->
                        val exportFile = pendingExport
                        pendingExport = null
                        if (uri == null || exportFile == null) {
                            ledgerViewModel.exportFinished("已取消导出")
                            return@rememberLauncherForActivityResult
                        }
                        runCatching {
                            context.contentResolver.openOutputStream(uri)?.use { output ->
                                output.write(exportFile.bytes)
                            } ?: error("Output stream is null")
                        }
                            .onSuccess { ledgerViewModel.exportFinished("账本已导出") }
                            .onFailure { ledgerViewModel.exportFinished("没有导出成功，可以换个保存位置再试。") }
                    }

                    LaunchedEffect(state.exportFile) {
                        val exportFile = state.exportFile ?: return@LaunchedEffect
                        pendingExport = exportFile
                        exportLauncher.launch(exportFile.fileName)
                        ledgerViewModel.exportLaunchHandled()
                    }

                    LedgerScreen(
                        state = state,
                        onMonthChange = ledgerViewModel::setMonthFilter,
                        onCategoryChange = ledgerViewModel::setCategoryFilter,
                        onQueryChange = ledgerViewModel::setQuery,
                        onClearFilters = ledgerViewModel::clearFilters,
                        onSync = ledgerViewModel::sync,
                        onExportCsv = ledgerViewModel::exportCsv,
                        onManualCreate = ledgerViewModel::createManualExpense,
                        onEdit = { editingExpense = it },
                    )
                }
                BottomTab.Stats -> {
                    val statsViewModel: StatsViewModel = viewModel(factory = repositoryFactory)
                    val state by statsViewModel.uiState.collectAsStateWithLifecycle()
                    StatsScreen(
                        state = state,
                        onMonthChange = statsViewModel::setMonth,
                        onRefresh = statsViewModel::refresh,
                    )
                }
                BottomTab.Recurring -> {
                    val recurringViewModel: RecurringViewModel = viewModel(
                        factory = recurringViewModelFactory(recurringRepository),
                    )
                    val state by recurringViewModel.uiState.collectAsStateWithLifecycle()
                    RecurringScreen(
                        state = state,
                        onRefresh = recurringViewModel::refresh,
                        onConfirmCandidate = recurringViewModel::confirmCandidate,
                        onPause = recurringViewModel::pause,
                        onResume = recurringViewModel::resume,
                        onArchive = recurringViewModel::archive,
                    )
                }
                BottomTab.Settings -> {
                    val settingsViewModel: SettingsViewModel = viewModel(
                        factory = settingsViewModelFactory,
                    )
                    val state by settingsViewModel.uiState.collectAsStateWithLifecycle()
                    SettingsScreen(
                        state = state,
                        currentSkin = currentSkin,
                        onTestConnection = settingsViewModel::testConnection,
                        onRunDiagnostics = settingsViewModel::runDiagnostics,
                        onRefreshServerSettings = settingsViewModel::refreshServerSettings,
                        onSync = settingsViewModel::sync,
                        onClearCache = settingsViewModel::clearLocalCache,
                        onSaveMonthlyBudget = settingsViewModel::saveMonthlyBudget,
                        onCreateRule = settingsViewModel::createCategoryRule,
                        onUpdateRule = settingsViewModel::updateCategoryRule,
                        onToggleRule = settingsViewModel::toggleCategoryRule,
                        onDeleteRule = settingsViewModel::deleteCategoryRule,
                        onSkinChange = onSkinChange,
                        onApplyBackgroundSettings = settingsViewModel::applyBackgroundSettings,
                        onClearBackgroundImage = settingsViewModel::clearBackgroundImage,
                        onBackgroundImageError = settingsViewModel::backgroundImageCopyFailed,
                        onImmersionModeChange = settingsViewModel::setImmersionMode,
                        onParallaxChange = settingsViewModel::setParallaxEnabled,
                        onReduceMotionChange = settingsViewModel::setReduceMotion,
                        onBindingCleared = onBindingCleared,
                        showAdvancedTools = BuildConfig.SHOW_ADVANCED_TOOLS,
                        ledgerRepository = ledgerRepository,
                        activeLedgerId = ledgerRepository.activeLedgerId(),
                        onBindingChanged = settingsViewModel::refreshLocalBindingState,
                        onLedgerSwitched = settingsViewModel::sync,
                    )
                }
            }
        }
    }
}
}

private val BottomTab.surfaceRole: SurfaceRole
    get() = when (this) {
        BottomTab.Pending -> SurfaceRole.Pending
        BottomTab.Ledger -> SurfaceRole.Ledger
        BottomTab.Stats -> SurfaceRole.Stats
        BottomTab.Recurring -> SurfaceRole.Stats
        BottomTab.Settings -> SurfaceRole.Settings
    }

private fun BottomTab.toBottomNavItem(): AppBottomNavItem = AppBottomNavItem(
    key = key,
    label = label,
    icon = icon,
)
