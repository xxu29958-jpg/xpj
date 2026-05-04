package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.screens.BindServerScreen
import com.ticketbox.ui.screens.ExpenseEditScreen
import com.ticketbox.ui.screens.LedgerScreen
import com.ticketbox.ui.screens.LoginScreen
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.screens.SettingsScreen
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.viewmodel.AppViewModel
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.LedgerViewModel
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.SettingsViewModel
import com.ticketbox.viewmodel.StatsViewModel
import com.ticketbox.viewmodel.expenseEditViewModelFactory
import com.ticketbox.viewmodel.repositoryViewModelFactory

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

    if (!appState.isBound) {
        BindServerScreen(
            loading = appState.binding,
            message = appState.authMessage,
            onBind = appViewModel::bind,
        )
        return
    }

    if (!appState.unlocked) {
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
        return
    }

    MainShell(
        repository = repository,
        settingsViewModelFactory = settingsViewModelFactory,
        onBindingCleared = {
            appViewModel.clearBinding()
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainShell(
    repository: ExpenseRepository,
    settingsViewModelFactory: ViewModelProvider.Factory,
    onBindingCleared: () -> Unit,
) {
    var selectedTab by remember { mutableStateOf(BottomTab.Pending) }
    var editingExpense by remember { mutableStateOf<Expense?>(null) }
    val repositoryFactory = repositoryViewModelFactory(repository)

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
        )
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("小票夹") })
        },
        bottomBar = {
            NavigationBar {
                BottomTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        androidx.compose.foundation.layout.Box(modifier = androidx.compose.ui.Modifier.padding(padding)) {
            when (selectedTab) {
                BottomTab.Pending -> {
                    val pendingViewModel: PendingViewModel = viewModel(factory = repositoryFactory)
                    val state by pendingViewModel.uiState.collectAsStateWithLifecycle()
                    PendingScreen(
                        state = state,
                        onRefresh = pendingViewModel::refresh,
                        onEdit = { editingExpense = it },
                        onConfirm = pendingViewModel::confirm,
                        onReject = pendingViewModel::reject,
                        onKeepDuplicate = pendingViewModel::markNotDuplicate,
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
                            } ?: error("无法写入文件")
                        }
                            .onSuccess { ledgerViewModel.exportFinished("账本已导出") }
                            .onFailure { ledgerViewModel.exportFinished(it.message ?: "导出失败") }
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
                        onClearFilters = ledgerViewModel::clearFilters,
                        onSync = ledgerViewModel::sync,
                        onExportCsv = ledgerViewModel::exportCsv,
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
                        onTestConnection = settingsViewModel::testConnection,
                        onRefreshServerSettings = settingsViewModel::refreshServerSettings,
                        onSync = settingsViewModel::sync,
                        onClearCache = settingsViewModel::clearLocalCache,
                        onCreateRule = settingsViewModel::createCategoryRule,
                        onUpdateRule = settingsViewModel::updateCategoryRule,
                        onToggleRule = settingsViewModel::toggleCategoryRule,
                        onDeleteRule = settingsViewModel::deleteCategoryRule,
                        onBindingCleared = onBindingCleared,
                    )
                }
            }
        }
    }
}
