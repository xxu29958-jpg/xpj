package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.screens.BindServerScreen
import com.ticketbox.ui.screens.ExpenseEditScreen
import com.ticketbox.ui.screens.LedgerScreen
import com.ticketbox.ui.screens.LoginScreen
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.screens.SettingsScreen
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.ui.theme.AppElevation
import com.ticketbox.ui.theme.AppRadius
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.AppUiState
import com.ticketbox.viewmodel.AppViewModel
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.LedgerViewModel
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.SettingsViewModel
import com.ticketbox.viewmodel.StatsViewModel
import com.ticketbox.viewmodel.expenseEditViewModelFactory
import com.ticketbox.viewmodel.repositoryViewModelFactory

private data class SelectedScreenshot(
    val fileName: String,
    val contentType: String?,
    val bytes: ByteArray,
)

private enum class BottomTab(
    val label: String,
    val icon: ImageVector,
) {
    Pending("待确认", Icons.Default.CheckCircle),
    Ledger("账本", Icons.AutoMirrored.Filled.ReceiptLong),
    Stats("统计", Icons.Default.BarChart),
    Settings("设置", Icons.Default.Settings),
}

@Composable
fun TicketboxApp(
    repository: ExpenseRepository,
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
            settingsViewModelFactory = settingsViewModelFactory,
            biometricAuthManager = biometricAuthManager,
        )
    }
}

@Composable
private fun TicketboxContent(
    appState: AppUiState,
    appViewModel: AppViewModel,
    repository: ExpenseRepository,
    settingsViewModelFactory: ViewModelProvider.Factory,
    biometricAuthManager: BiometricAuthManager,
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
                onBind = appViewModel::bind,
            )
        }
        return
    }

    if (!appState.unlocked) {
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
        settingsViewModelFactory = settingsViewModelFactory,
        currentSkin = appState.skin,
        backgroundSettings = appState.backgroundSettings,
        onSkinChange = appViewModel::selectSkin,
        onBindingCleared = {
            appViewModel.clearBinding()
        },
    )
}

@Composable
private fun MainShell(
    repository: ExpenseRepository,
    settingsViewModelFactory: ViewModelProvider.Factory,
    currentSkin: AppSkin,
    backgroundSettings: BackgroundSettings,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    var selectedTab by remember { mutableStateOf(BottomTab.Pending) }
    var editingExpense by remember { mutableStateOf<Expense?>(null) }
    val repositoryFactory = repositoryViewModelFactory(repository)
    val currentRole = editingExpense?.let { SurfaceRole.Edit } ?: selectedTab.surfaceRole

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
            bottomBar = {
                TicketboxBottomBar(
                    selectedTab = selectedTab,
                    onSelectTab = { selectedTab = it },
                )
            },
        ) { padding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                when (selectedTab) {
                BottomTab.Pending -> {
                    val pendingViewModel: PendingViewModel = viewModel(factory = repositoryFactory)
                    val state by pendingViewModel.uiState.collectAsStateWithLifecycle()
                    val context = LocalContext.current
                    val imagePickerLauncher = rememberLauncherForActivityResult(
                        contract = ActivityResultContracts.PickVisualMedia(),
                    ) { uri ->
                        val selected = uri?.let { context.readSelectedScreenshot(it) } ?: return@rememberLauncherForActivityResult
                        pendingViewModel.uploadScreenshot(
                            fileName = selected.fileName,
                            contentType = selected.contentType,
                            bytes = selected.bytes,
                        )
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
                        onImmersionModeChange = settingsViewModel::setImmersionMode,
                        onParallaxChange = settingsViewModel::setParallaxEnabled,
                        onReduceMotionChange = settingsViewModel::setReduceMotion,
                        onBindingCleared = onBindingCleared,
                        showAdvancedTools = BuildConfig.SHOW_ADVANCED_TOOLS,
                    )
                }
            }
        }
    }
}
}

@Composable
private fun TicketboxBottomBar(
    selectedTab: BottomTab,
    onSelectTab: (BottomTab) -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(start = 20.dp, end = 20.dp, top = 10.dp, bottom = 10.dp),
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(AppRadius.bottomBar),
            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
            tonalElevation = 0.dp,
            shadowElevation = AppElevation.floatingBottomBarShadow,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                BottomTab.entries.forEach { tab ->
                    BottomBarItem(
                        tab = tab,
                        selected = selectedTab == tab,
                        onClick = { onSelectTab(tab) },
                    )
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
        BottomTab.Settings -> SurfaceRole.Settings
    }

@Composable
private fun BottomBarItem(
    tab: BottomTab,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val background by animateColorAsState(
        targetValue = if (selected) MaterialTheme.colorScheme.primary else Color.Transparent,
        label = "bottomTabBackground",
    )
    val content by animateColorAsState(
        targetValue = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        label = "bottomTabContent",
    )
    if (selected) {
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.large))
                .clickable(onClick = onClick)
                .background(background)
                .padding(horizontal = 16.dp, vertical = 13.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = tab.icon,
                contentDescription = tab.label,
                tint = content,
                modifier = Modifier.size(19.dp),
            )
            Text(
                text = tab.label,
                color = content,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Black,
            )
        }
    } else {
        Column(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.large))
                .clickable(onClick = onClick)
                .padding(horizontal = 14.dp, vertical = 8.dp),
            horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Icon(
                imageVector = tab.icon,
                contentDescription = tab.label,
                tint = content,
                modifier = Modifier.size(19.dp),
            )
            Text(
                text = tab.label,
                color = content,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

private fun Context.readSelectedScreenshot(uri: Uri): SelectedScreenshot? {
    val contentType = contentResolver.getType(uri)
    val fileName = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
        ?.use { cursor ->
            val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
        }
        ?.trim()
        ?.takeIf { it.isNotBlank() }
        ?: defaultScreenshotFileName(contentType)
    val bytes = contentResolver.openInputStream(uri)?.use { input -> input.readBytes() } ?: return null
    return SelectedScreenshot(fileName = fileName, contentType = contentType, bytes = bytes)
}

private fun defaultScreenshotFileName(contentType: String?): String {
    val extension = when (contentType?.lowercase()) {
        "image/png" -> "png"
        "image/webp" -> "webp"
        "image/heic", "image/heif" -> "heic"
        else -> "jpg"
    }
    return "ticketbox-screenshot.$extension"
}
