package com.ticketbox.ui.navigation

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.integerResource
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.TagRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.ui.appearance.background.BackgroundImageStore
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.BillSplitScreen
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.screens.settings.AboutScreen
import com.ticketbox.ui.screens.settings.AppearanceScreen
import com.ticketbox.ui.screens.settings.BackgroundCropScreen
import com.ticketbox.ui.screens.settings.BackgroundGalleryScreen
import com.ticketbox.ui.screens.settings.BackgroundPreviewScreen
import com.ticketbox.ui.screens.settings.BackgroundTasksScreen
import com.ticketbox.ui.screens.settings.CategoryRulesScreen
import com.ticketbox.ui.screens.settings.DashboardCardsScreen
import com.ticketbox.ui.screens.settings.DataExportScreen
import com.ticketbox.ui.screens.settings.FamilyMembersScreen
import com.ticketbox.ui.screens.settings.JoinFamilyLedgerScreen
import com.ticketbox.ui.screens.settings.LedgerSwitcherScreen
import com.ticketbox.ui.screens.settings.MerchantAliasesScreen
import com.ticketbox.ui.screens.settings.MyDevicesScreen
import com.ticketbox.ui.screens.settings.NotificationPreferencesScreen
import com.ticketbox.ui.screens.settings.RecycleBinScreen
import com.ticketbox.ui.screens.settings.SecurityPrivacyScreen
import com.ticketbox.ui.screens.settings.ServerSettingsScreen
import com.ticketbox.ui.screens.settings.SettingsRootScreen
import com.ticketbox.ui.screens.settings.SettingsRoute as SettingsDestination
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.ui.screens.settings.TagManagementScreen
import com.ticketbox.viewmodel.AppearanceUiState
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import com.ticketbox.viewmodel.BillSplitViewModel
import com.ticketbox.viewmodel.CategoryRulesUiState
import com.ticketbox.viewmodel.DashboardCardsViewModel
import com.ticketbox.viewmodel.FamilyMembersViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel
import com.ticketbox.viewmodel.LedgerSwitcherViewModel
import com.ticketbox.viewmodel.MerchantAliasUiState
import com.ticketbox.viewmodel.MyDevicesViewModel
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.RecycleBinViewModel
import com.ticketbox.viewmodel.SettingsUiState
import com.ticketbox.viewmodel.TagManagementViewModel
import com.ticketbox.viewmodel.backgroundTasksViewModelFactory
import com.ticketbox.viewmodel.billSplitViewModelFactory
import com.ticketbox.viewmodel.dashboardCardsViewModelFactory
import com.ticketbox.viewmodel.familyMembersViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.joinFamilyLedgerViewModelFactory
import com.ticketbox.viewmodel.ledgerSwitcherViewModelFactory
import com.ticketbox.viewmodel.myDevicesViewModelFactory
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import com.ticketbox.viewmodel.recycleBinViewModelFactory
import com.ticketbox.viewmodel.tagManagementViewModelFactory

internal data class SettingsRouteStates(
    val settings: SettingsUiState,
    val rules: CategoryRulesUiState,
    val merchant: MerchantAliasUiState,
    val appearance: AppearanceUiState,
)

internal data class SettingsRouteActions(
    val onTestConnection: () -> Unit,
    val onRunDiagnostics: () -> Unit,
    val onRefreshServerSettings: () -> Unit,
    val onSync: () -> Unit,
    val onClearCache: () -> Unit,
    val onSaveNotificationPreferences: (NotificationPreferences) -> Unit,
    val onCreateRule: (String, String, Int) -> Unit,
    val onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    val onToggleRule: (CategoryRule) -> Unit,
    val onDeleteRule: (CategoryRule) -> Unit,
    val onUndoRuleDelete: () -> Unit,
    val onDismissRuleUndo: () -> Unit,
    val onCreateMerchantCatalog: (String) -> Unit,
    val onRenameMerchantCatalog: (MerchantCatalog, String) -> Unit,
    val onToggleMerchantCatalog: (MerchantCatalog) -> Unit,
    val onMergeMerchantCatalog: (MerchantCatalog, MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    val onDeleteMerchantCatalog: (MerchantCatalog) -> Unit,
    val onCreateMerchantAlias: (String, String) -> Unit,
    val onToggleMerchantAlias: (MerchantAlias) -> Unit,
    val onDeleteMerchantAlias: (MerchantAlias) -> Unit,
    val onUndoMerchantAlias: () -> Unit,
    val onDismissMerchantAliasUndo: () -> Unit,
    val onDismissMerchantCatalogMergeSuggestion: () -> Unit,
    val onPreviewApplyConfirmedRules: () -> Unit,
    val onConfirmApplyConfirmedRules: () -> Unit,
    val onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
    val onSkinChange: (AppSkin) -> Unit,
    val onCurrencyChange: (CurrencyCode) -> Unit,
    val onApplyBackgroundSettings: (BackgroundSettings) -> Unit,
    val onClearBackgroundImage: () -> Unit,
    val onBackgroundImageError: (String) -> Unit,
    val onImmersionModeChange: (ImmersionMode) -> Unit,
    val onParallaxChange: (Boolean) -> Unit,
    val onReduceMotionChange: (Boolean) -> Unit,
    val onBindingCleared: () -> Unit,
    val onBindingChanged: () -> Unit,
    val onLedgerSwitched: () -> Unit,
    val onDashboardCardsChanged: () -> Unit,
)

internal data class SettingsRouteRepositories(
    val ledgerRepository: LedgerRepository,
    val expenseRepository: ExpenseRepository,
    val reportsRepository: ReportsActions,
    val incomePlanRepository: IncomePlanActions,
    val outboxRepository: OutboxRepository,
    val tagRepository: TagRepository,
    val activeLedgerId: String?,
)

@Composable
internal fun SettingsDestinationHost(
    states: SettingsRouteStates,
    currentSkin: AppSkin,
    currentCurrency: CurrencyCode,
    showAdvancedTools: Boolean,
    actions: SettingsRouteActions,
    repositories: SettingsRouteRepositories,
) {
    var route by remember { mutableStateOf<SettingsDestination>(SettingsDestination.Root) }
    val context = LocalContext.current
    val backgroundImageStore = remember(context) { BackgroundImageStore(context) }
    val appVersionName = stringResource(R.string.app_version_name)
    val appVersionCode = integerResource(R.integer.app_version_code)
    // Resolve strings before launcher callbacks and runCatching handlers need them.
    val backgroundCopyFailedMessage = stringResource(R.string.settings_background_copy_failed)
    val backgroundCustomTitle = stringResource(R.string.settings_background_custom_title)
    val backgroundCropFailedMessage = stringResource(R.string.settings_background_crop_failed)

    val backgroundPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        runCatching {
            backgroundImageStore.copyPickedImageToPrivateStorage(uri)
        }
            .onSuccess { path -> route = SettingsDestination.BackgroundCrop(path) }
            .onFailure { actions.onBackgroundImageError(backgroundCopyFailedMessage) }
    }

    fun launchImagePicker() {
        backgroundPickerLauncher.launch(
            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
        )
    }

    fun previewThemeDefault() {
        actions.onApplyBackgroundSettings(states.appearance.backgroundSettings.withoutBackground())
    }

    BackHandler(enabled = route != SettingsDestination.Root) {
        route = when (route) {
            SettingsDestination.BackgroundGallery,
            is SettingsDestination.BackgroundCrop,
            is SettingsDestination.BackgroundPreview,
            -> SettingsDestination.Appearance
            else -> SettingsDestination.Root
        }
    }

    when (val currentRoute = route) {
        SettingsDestination.Root -> SettingsRootScreen(
            state = states.settings,
            showAdvancedTools = showAdvancedTools,
            onOpenServer = { route = SettingsDestination.Server },
            onOpenAppearance = { route = SettingsDestination.Appearance },
            onOpenDashboardCards = { route = SettingsDestination.DashboardCards },
            onOpenCategoryRules = { route = SettingsDestination.CategoryRules },
            onOpenMerchantAliases = { route = SettingsDestination.MerchantAliases },
            onOpenTagManagement = { route = SettingsDestination.TagManagement },
            onOpenRecycleBin = { route = SettingsDestination.RecycleBin },
            onOpenDataExport = { route = SettingsDestination.DataExport },
            onOpenNotifications = { route = SettingsDestination.NotificationPreferences },
            onOpenSecurity = { route = SettingsDestination.SecurityPrivacy },
            onOpenLedgers = { route = SettingsDestination.Ledgers },
            onOpenFamilyMembers = { route = SettingsDestination.FamilyMembers },
            onOpenMyDevices = { route = SettingsDestination.MyDevices },
            onOpenJoinFamilyLedger = { route = SettingsDestination.JoinFamilyLedger },
            onOpenBillSplits = { route = SettingsDestination.BillSplits },
            onOpenBackgroundTasks = { route = SettingsDestination.BackgroundTasks },
            onOpenSyncStatus = { route = SettingsDestination.SyncStatus },
            onOpenIncomePlans = { route = SettingsDestination.IncomePlans },
            onOpenAbout = { route = SettingsDestination.About },
        )

        SettingsDestination.Server -> ServerSettingsScreen(
            state = states.settings,
            showAdvancedTools = showAdvancedTools,
            onBack = { route = SettingsDestination.Root },
            onTestConnection = actions.onTestConnection,
            onRunDiagnostics = actions.onRunDiagnostics,
            onRefreshServerSettings = actions.onRefreshServerSettings,
            onSync = actions.onSync,
        )

        SettingsDestination.Appearance -> AppearanceScreen(
            state = states.appearance,
            currentSkin = currentSkin,
            currentCurrency = currentCurrency,
            onBack = { route = SettingsDestination.Root },
            onSkinChange = actions.onSkinChange,
            onCurrencyChange = actions.onCurrencyChange,
            onOpenGallery = { route = SettingsDestination.BackgroundGallery },
            onPickCustomImage = ::launchImagePicker,
            onPreviewThemeDefault = ::previewThemeDefault,
            onClearBackgroundImage = {
                backgroundImageStore.deleteCustomBackground(states.appearance.backgroundSettings.customImagePath)
                actions.onClearBackgroundImage()
            },
            onImmersionModeChange = actions.onImmersionModeChange,
            onParallaxChange = actions.onParallaxChange,
            onReduceMotionChange = actions.onReduceMotionChange,
        )

        SettingsDestination.BackgroundGallery -> BackgroundGalleryScreen(
            currentSettings = states.appearance.backgroundSettings,
            onBack = { route = SettingsDestination.Appearance },
            onPickCustomImage = ::launchImagePicker,
            onPreviewThemeDefault = ::previewThemeDefault,
            onPreviewBuiltIn = { background, title ->
                route = SettingsDestination.BackgroundPreview(
                    settings = states.appearance.backgroundSettings.withBuiltInBackground(background.id),
                    title = title,
                )
            },
        )

        is SettingsDestination.BackgroundCrop -> BackgroundCropScreen(
            sourcePath = currentRoute.sourcePath,
            onBack = { route = SettingsDestination.Appearance },
            onComplete = { cropMode ->
                runCatching {
                    backgroundImageStore.cropPickedImageToPrivateStorage(
                        sourcePath = currentRoute.sourcePath,
                        cropMode = cropMode,
                    )
                }
                    .onSuccess { croppedPath ->
                        route = SettingsDestination.BackgroundPreview(
                            settings = states.appearance.backgroundSettings
                                .withCustomImage(croppedPath)
                                .copy(cropMode = cropMode),
                            title = backgroundCustomTitle,
                        )
                    }
                    .onFailure { actions.onBackgroundImageError(backgroundCropFailedMessage) }
            },
        )

        is SettingsDestination.BackgroundPreview -> BackgroundPreviewScreen(
            initialSettings = currentRoute.settings,
            currentSkin = currentSkin,
            title = currentRoute.title,
            onBack = { route = SettingsDestination.Appearance },
            onApply = { settings ->
                actions.onApplyBackgroundSettings(settings)
                route = SettingsDestination.Appearance
            },
        )

        SettingsDestination.DashboardCards -> {
            val vm: DashboardCardsViewModel = viewModel(
                key = "settings-dashboard-cards",
                factory = dashboardCardsViewModelFactory(repositories.reportsRepository),
            )
            val state by vm.uiState.collectAsStateWithLifecycle()
            LaunchedEffect(state.savedRevision) {
                if (state.savedRevision > 0) actions.onDashboardCardsChanged()
            }
            DashboardCardsScreen(
                state = state,
                onBack = { route = SettingsDestination.Root },
                actions = com.ticketbox.ui.screens.settings.DashboardCardsScreenActions(
                    onMoveCard = vm::moveCard,
                    onReorder = vm::reorderCards,
                    onVisibleChange = vm::setVisible,
                    onSave = vm::saveCards,
                    onReset = vm::resetCards,
                ),
            )
        }

        SettingsDestination.CategoryRules -> CategoryRulesScreen(
            rules = states.rules.categoryRules,
            busy = states.rules.busy,
            readOnly = !ledgerRoleCanModify(states.settings.role),
            message = states.rules.message,
            onBack = { route = SettingsDestination.Root },
            onCreateRule = actions.onCreateRule,
            onUpdateRule = actions.onUpdateRule,
            onToggleRule = actions.onToggleRule,
            onDeleteRule = actions.onDeleteRule,
            applications = states.rules.ruleApplications,
            confirmedPreview = states.rules.confirmedRulesPreview,
            onPreviewApplyConfirmedRules = actions.onPreviewApplyConfirmedRules,
            onConfirmApplyConfirmedRules = actions.onConfirmApplyConfirmedRules,
            onRollbackRuleApplication = actions.onRollbackRuleApplication,
            undoableRule = states.rules.undoableRule,
            onUndoDelete = actions.onUndoRuleDelete,
            onDismissUndo = actions.onDismissRuleUndo,
        )

        SettingsDestination.MerchantAliases -> MerchantAliasesScreen(
            catalog = states.merchant.merchantCatalog,
            aliases = states.merchant.merchantAliases,
            busy = states.merchant.busy,
            readOnly = !ledgerRoleCanModify(states.settings.role),
            message = states.merchant.message,
            onBack = { route = SettingsDestination.Root },
            onCreateCatalog = actions.onCreateMerchantCatalog,
            onRenameCatalog = actions.onRenameMerchantCatalog,
            onToggleCatalog = actions.onToggleMerchantCatalog,
            onMergeCatalog = actions.onMergeMerchantCatalog,
            onDeleteCatalog = actions.onDeleteMerchantCatalog,
            onCreateAlias = actions.onCreateMerchantAlias,
            onToggleAlias = actions.onToggleMerchantAlias,
            onDeleteAlias = actions.onDeleteMerchantAlias,
            undoableAlias = states.merchant.undoableAlias,
            mergeSuggestion = states.merchant.mergeSuggestion,
            onDismissMergeSuggestion = actions.onDismissMerchantCatalogMergeSuggestion,
            onUndoDelete = actions.onUndoMerchantAlias,
            onDismissUndo = actions.onDismissMerchantAliasUndo,
        )

        SettingsDestination.TagManagement -> {
            val vm: TagManagementViewModel = viewModel(
                // Key by ledger so switching ledgers gets a fresh VM (fresh load),
                // not the previous ledger's tags / undo handle / message.
                key = "tag-management-${repositories.activeLedgerId ?: "none"}",
                factory = tagManagementViewModelFactory(repositories.tagRepository),
            )
            TagManagementScreen(
                viewModel = vm,
                readOnly = !ledgerRoleCanModify(states.settings.role),
                onBack = { route = SettingsDestination.Root },
                // P4 stale-refresh: a committed tag mutation reuses the stats-refresh
                // signal so the stats tab re-pulls its tag list (drops the dead chip)
                // on next show — same validated channel as dashboard-card edits.
                onTagsChanged = actions.onDashboardCardsChanged,
            )
        }

        SettingsDestination.RecycleBin -> {
            val vm: RecycleBinViewModel = viewModel(
                factory = recycleBinViewModelFactory(repositories.ledgerRepository),
            )
            RecycleBinScreen(
                viewModel = vm,
                onBack = { route = SettingsDestination.Root },
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

        SettingsDestination.BillSplits -> {
            val vm: BillSplitViewModel = viewModel(
                key = "bill-splits",
                factory = billSplitViewModelFactory(
                    repositories.expenseRepository,
                    repositories.ledgerRepository,
                ),
            )
            BillSplitScreen(
                viewModel = vm,
                onBack = { route = SettingsDestination.Root },
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

        SettingsDestination.IncomePlans -> {
            val vm: IncomePlanViewModel = viewModel(
                key = IncomePlanViewModelKey,
                factory = incomePlanViewModelFactory(repositories.incomePlanRepository),
            )
            IncomePlanScreen(
                viewModel = vm,
                currency = LocalCurrencyDisplay.current,
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
