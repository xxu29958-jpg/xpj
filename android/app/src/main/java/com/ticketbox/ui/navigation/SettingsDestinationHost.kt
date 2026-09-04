package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.integerResource
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.screens.settings.AboutScreen
import com.ticketbox.ui.screens.settings.AppearanceBackgroundActions
import com.ticketbox.ui.screens.settings.AppearanceImmersionActions
import com.ticketbox.ui.screens.settings.AppearancePreferenceActions
import com.ticketbox.ui.screens.settings.AppearancePreferenceState
import com.ticketbox.ui.screens.settings.AppearanceScreen
import com.ticketbox.ui.screens.settings.AppearanceScreenActions
import com.ticketbox.ui.screens.settings.AppearanceScreenState
import com.ticketbox.ui.screens.settings.BackgroundEditorActions
import com.ticketbox.ui.screens.settings.BackgroundEditorScreen
import com.ticketbox.ui.screens.settings.BackgroundGalleryScreen
import com.ticketbox.ui.screens.settings.BackgroundTasksScreen
import com.ticketbox.ui.screens.settings.DataExportScreen
import com.ticketbox.ui.screens.settings.FamilyMembersScreen
import com.ticketbox.ui.screens.settings.JoinFamilyLedgerScreen
import com.ticketbox.ui.screens.settings.LedgerSwitcherScreen
import com.ticketbox.ui.screens.settings.MyDevicesScreen
import com.ticketbox.ui.screens.settings.NotificationPreferencesScreen
import com.ticketbox.ui.screens.settings.SecurityPrivacyScreen
import com.ticketbox.ui.screens.settings.ServerSettingsScreen
import com.ticketbox.ui.screens.settings.ServerSettingsScreenActions
import com.ticketbox.ui.screens.settings.ServerSettingsScreenState
import com.ticketbox.ui.screens.settings.SettingsRootAlertsAppearanceNavigationActions
import com.ticketbox.ui.screens.settings.SettingsRootConnectionSystemNavigationActions
import com.ticketbox.ui.screens.settings.SettingsRootDataPrivacyNavigationActions
import com.ticketbox.ui.screens.settings.SettingsRootLedgerFamilyNavigationActions
import com.ticketbox.ui.screens.settings.SettingsRootNavigationActions
import com.ticketbox.ui.screens.settings.SettingsRootScreen
import com.ticketbox.ui.screens.settings.SettingsRoute as SettingsDestination
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.viewmodel.AppearanceUiState
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import com.ticketbox.viewmodel.FamilyMembersViewModel
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel
import com.ticketbox.viewmodel.LedgerSwitcherViewModel
import com.ticketbox.viewmodel.MyDevicesViewModel
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.SettingsUiState
import com.ticketbox.viewmodel.backgroundTasksViewModelFactory
import com.ticketbox.viewmodel.familyMembersViewModelFactory
import com.ticketbox.viewmodel.joinFamilyLedgerViewModelFactory
import com.ticketbox.viewmodel.ledgerSwitcherViewModelFactory
import com.ticketbox.viewmodel.myDevicesViewModelFactory
import com.ticketbox.viewmodel.outboxStatusViewModelFactory

internal data class SettingsRouteStates(
    val settings: SettingsUiState,
    val appearance: AppearanceUiState,
)

internal data class SettingsDestinationChromeState(
    val currentSkin: AppSkin,
    val currentMode: AppThemeMode,
    val currentCurrency: CurrencyCode,
    val showAdvancedTools: Boolean,
)

internal data class SettingsDestinationNavigation(
    val onSecondaryActiveChange: (Boolean) -> Unit = {},
    val onCloseRoot: () -> Unit = {},
)

internal data class SettingsRouteActions(
    val onTestConnection: () -> Unit,
    val onRunDiagnostics: () -> Unit,
    val onRefreshServerSettings: () -> Unit,
    val onSync: () -> Unit,
    val onClearCache: () -> Unit,
    val onSaveNotificationPreferences: (NotificationPreferences) -> Unit,
    val onThemeModeChange: (AppThemeMode) -> Unit,
    val onCurrencyChange: (CurrencyCode) -> Unit,
    // 全局背景批:导入 / 编辑 draft / 取消 / 应用全部由 AppearanceViewModel 唯一持有,
    // UI 只转发意图,不碰文件与偏好写入。
    val onImportBackgroundImage: (Uri) -> Unit,
    val onEditBackground: (BackgroundSettings) -> Unit,
    val onUpdateBackgroundDraft: (BackgroundSettings) -> Unit,
    val onCancelBackgroundEdit: () -> Unit,
    val onApplyBackgroundDraft: () -> Unit,
    val onClearBackgroundImage: () -> Unit,
    val onImmersionModeChange: (ImmersionMode) -> Unit,
    val onParallaxChange: (Boolean) -> Unit,
    val onReduceMotionChange: (Boolean) -> Unit,
    val onBindingCleared: () -> Unit,
    val onBindingChanged: () -> Unit,
    val onLedgerSwitched: () -> Unit,
)

internal data class SettingsRouteRepositories(
    val ledgerRepository: LedgerRepository,
    val expenseRepository: ExpenseRepository,
    val outboxRepository: OutboxRepository,
    val activeLedgerId: String?,
)

@Composable
internal fun SettingsDestinationHost(
    states: SettingsRouteStates,
    chromeState: SettingsDestinationChromeState,
    navigation: SettingsDestinationNavigation = SettingsDestinationNavigation(),
    actions: SettingsRouteActions,
    repositories: SettingsRouteRepositories,
) {
    var route by remember { mutableStateOf<SettingsDestination>(SettingsDestination.Root) }
    val appVersionName = stringResource(R.string.app_version_name)
    val appVersionCode = integerResource(R.integer.app_version_code)

    LaunchedEffect(route) {
        navigation.onSecondaryActiveChange(route != SettingsDestination.Root)
    }
    DisposableEffect(Unit) {
        onDispose { navigation.onSecondaryActiveChange(false) }
    }

    // 状态驱动导航:editor 出现(导入成功 / 调整构图 / 选内置)→进编辑面;
    // editor 消失(取消或应用成功)→回外观页。取消的候选图清理由 VM 完成。
    val backgroundEditorOpen = states.appearance.editor != null
    LaunchedEffect(backgroundEditorOpen) {
        if (backgroundEditorOpen && route != SettingsDestination.BackgroundEditor) {
            route = SettingsDestination.BackgroundEditor
        } else if (!backgroundEditorOpen && route == SettingsDestination.BackgroundEditor) {
            route = SettingsDestination.Appearance
        }
    }

    val backgroundPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        actions.onImportBackgroundImage(uri)
    }

    fun launchImagePicker() {
        backgroundPickerLauncher.launch(
            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
        )
    }

    BackHandler {
        when (route) {
            SettingsDestination.Root -> navigation.onCloseRoot()
            // 编辑面返回 = 取消:VM 丢弃 draft 与候选文件,状态收敛后路由自动回外观页。
            SettingsDestination.BackgroundEditor -> actions.onCancelBackgroundEdit()
            SettingsDestination.BackgroundGallery -> route = SettingsDestination.Appearance
            else -> route = SettingsDestination.Root
        }
    }

    when (route) {
        SettingsDestination.Root -> SettingsRootScreen(
            state = states.settings,
            showAdvancedTools = chromeState.showAdvancedTools,
            onBack = navigation.onCloseRoot,
            navigationActions = SettingsRootNavigationActions(
                ledgerFamily = SettingsRootLedgerFamilyNavigationActions(
                    onOpenLedgers = { route = SettingsDestination.Ledgers },
                    onOpenFamilyMembers = { route = SettingsDestination.FamilyMembers },
                    onOpenMyDevices = { route = SettingsDestination.MyDevices },
                    onOpenJoinFamilyLedger = { route = SettingsDestination.JoinFamilyLedger },
                ),
                dataPrivacy = SettingsRootDataPrivacyNavigationActions(
                    onOpenDataExport = { route = SettingsDestination.DataExport },
                ),
                alertsAppearance = SettingsRootAlertsAppearanceNavigationActions(
                    onOpenNotifications = { route = SettingsDestination.NotificationPreferences },
                    onOpenAppearance = { route = SettingsDestination.Appearance },
                ),
                connectionSystem = SettingsRootConnectionSystemNavigationActions(
                    onOpenServer = { route = SettingsDestination.Server },
                    onOpenSyncStatus = { route = SettingsDestination.SyncStatus },
                    onOpenBackgroundTasks = { route = SettingsDestination.BackgroundTasks },
                    onOpenSecurity = { route = SettingsDestination.SecurityPrivacy },
                    onOpenAbout = { route = SettingsDestination.About },
                ),
            ),
        )

        SettingsDestination.Server -> ServerSettingsScreen(
            state = ServerSettingsScreenState(
                settings = states.settings,
                showAdvancedTools = chromeState.showAdvancedTools,
            ),
            actions = ServerSettingsScreenActions(
                onBack = { route = SettingsDestination.Root },
                onTestConnection = actions.onTestConnection,
                onRunDiagnostics = actions.onRunDiagnostics,
                onRefreshServerSettings = actions.onRefreshServerSettings,
                onSync = actions.onSync,
            ),
        )

        SettingsDestination.Appearance -> AppearanceScreen(
            state = AppearanceScreenState(
                appearance = states.appearance,
                preferences = AppearancePreferenceState(
                    currentSkin = chromeState.currentSkin,
                    currentMode = chromeState.currentMode,
                    currentCurrency = chromeState.currentCurrency,
                ),
            ),
            actions = AppearanceScreenActions(
                onBack = { route = SettingsDestination.Root },
                preferences = AppearancePreferenceActions(
                    onThemeModeChange = actions.onThemeModeChange,
                    onCurrencyChange = actions.onCurrencyChange,
                ),
                background = AppearanceBackgroundActions(
                    onOpenGallery = { route = SettingsDestination.BackgroundGallery },
                    onPickCustomImage = ::launchImagePicker,
                    onEditBackground = actions.onEditBackground,
                    onClearBackgroundImage = actions.onClearBackgroundImage,
                ),
                immersion = AppearanceImmersionActions(
                    onModeChange = actions.onImmersionModeChange,
                    onParallaxChange = actions.onParallaxChange,
                    onReduceMotionChange = actions.onReduceMotionChange,
                ),
            ),
        )

        SettingsDestination.BackgroundGallery -> BackgroundGalleryScreen(
            currentSettings = states.appearance.backgroundSettings,
            onBack = { route = SettingsDestination.Appearance },
            onPickCustomImage = ::launchImagePicker,
            onRestoreTheme = actions.onClearBackgroundImage,
            onPreviewBuiltIn = { background ->
                actions.onEditBackground(
                    states.appearance.backgroundSettings.withBuiltInBackground(background.id),
                )
            },
        )

        // editor 为空的瞬态(取消/应用成功后的路由切换间隙)不渲染内容,
        // LaunchedEffect 会把 route 收回 Appearance。
        SettingsDestination.BackgroundEditor -> states.appearance.editor?.let { editor ->
            BackgroundEditorScreen(
                editor = editor,
                currentSkin = chromeState.currentSkin,
                actions = BackgroundEditorActions(
                    onDraftChange = actions.onUpdateBackgroundDraft,
                    onCancel = actions.onCancelBackgroundEdit,
                    onApply = actions.onApplyBackgroundDraft,
                ),
            )
        }

        SettingsDestination.DataExport -> DataExportScreen(
            state = states.settings,
            onBack = { route = SettingsDestination.Root },
            onSync = actions.onSync,
            onClearCache = actions.onClearCache,
        )

        SettingsDestination.NotificationPreferences -> NotificationPreferencesScreen(
            preferences = states.settings.notificationPreferences,
            readOnly = !ledgerRoleCanModify(states.settings.role),
            // Revives the previously silent save feedback: SettingsViewModel
            // already writes message + tone; surface it in the page-header slot.
            status = { AppStatusBanner(message = states.settings.message, tone = states.settings.messageTone) },
            onBack = { route = SettingsDestination.Root },
            onSave = actions.onSaveNotificationPreferences,
        )

        SettingsDestination.SecurityPrivacy -> SecurityPrivacyScreen(
            onBack = { route = SettingsDestination.Root },
            onClearCache = actions.onClearCache,
            onBindingCleared = actions.onBindingCleared,
            busy = states.settings.busy,
            // Revives the previously silent clear-cache / logout feedback.
            status = { AppStatusBanner(message = states.settings.message, tone = states.settings.messageTone) },
        )

        SettingsDestination.Ledgers -> {
            val vm: LedgerSwitcherViewModel = viewModel(
                key = "ledger-switcher",
                factory = ledgerSwitcherViewModelFactory(repositories.ledgerRepository),
            )
            LedgerSwitcherScreen(
                viewModel = vm,
                activeLedgerId = repositories.activeLedgerId,
                onBack = { route = SettingsDestination.Root },
                onSwitched = actions.onLedgerSwitched,
            )
        }

        SettingsDestination.FamilyMembers -> {
            val vm: FamilyMembersViewModel = viewModel(
                key = "family-members",
                factory = familyMembersViewModelFactory(repositories.ledgerRepository),
            )
            FamilyMembersScreen(
                viewModel = vm,
                activeLedgerId = repositories.activeLedgerId,
                currentRole = states.settings.role,
                onBack = { route = SettingsDestination.Root },
                onMembershipChanged = actions.onBindingChanged,
            )
        }

        SettingsDestination.MyDevices -> {
            val vm: MyDevicesViewModel = viewModel(
                key = "my-devices",
                factory = myDevicesViewModelFactory(repositories.ledgerRepository),
            )
            MyDevicesScreen(
                viewModel = vm,
                activeLedgerId = repositories.activeLedgerId,
                onBack = { route = SettingsDestination.Root },
            )
        }

        SettingsDestination.JoinFamilyLedger -> {
            val vm: JoinFamilyLedgerViewModel = viewModel(
                key = "join-family-ledger",
                factory = joinFamilyLedgerViewModelFactory(repositories.ledgerRepository),
            )
            JoinFamilyLedgerScreen(
                viewModel = vm,
                onBack = { route = SettingsDestination.Root },
                onAccepted = {
                    actions.onBindingChanged()
                    actions.onLedgerSwitched()
                    route = SettingsDestination.Ledgers
                },
            )
        }

        SettingsDestination.BackgroundTasks -> {
            val vm: BackgroundTasksViewModel = viewModel(
                key = "background-tasks",
                factory = backgroundTasksViewModelFactory(repositories.expenseRepository),
            )
            BackgroundTasksScreen(
                viewModel = vm,
                onBack = { route = SettingsDestination.Root },
            )
        }

        SettingsDestination.SyncStatus -> {
            val vm: OutboxStatusViewModel = viewModel(
                key = "sync-status",
                factory = outboxStatusViewModelFactory(
                    repositories.outboxRepository,
                    repositories.expenseRepository,
                ),
            )
            SyncStatusScreen(
                viewModel = vm,
                onBack = { route = SettingsDestination.Root },
            )
        }

        SettingsDestination.About -> AboutScreen(
            appVersionName = appVersionName,
            appVersionCode = appVersionCode,
            onBack = { route = SettingsDestination.Root },
        )
    }
}
