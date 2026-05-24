package com.ticketbox.ui.navigation

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.integerResource
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.ui.appearance.background.BackgroundImageStore
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
import com.ticketbox.ui.screens.settings.NotificationPreferencesScreen
import com.ticketbox.ui.screens.settings.SecurityPrivacyScreen
import com.ticketbox.ui.screens.settings.ServerSettingsScreen
import com.ticketbox.ui.screens.settings.SettingsRootScreen
import com.ticketbox.ui.screens.settings.SettingsRoute as SettingsDestination
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import com.ticketbox.viewmodel.BillSplitViewModel
import com.ticketbox.viewmodel.FamilyMembersViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel
import com.ticketbox.viewmodel.LedgerSwitcherViewModel
import com.ticketbox.viewmodel.SettingsUiState
import com.ticketbox.viewmodel.backgroundTasksViewModelFactory
import com.ticketbox.viewmodel.billSplitViewModelFactory
import com.ticketbox.viewmodel.familyMembersViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.joinFamilyLedgerViewModelFactory
import com.ticketbox.viewmodel.ledgerSwitcherViewModelFactory

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
    val onCreateMerchantAlias: (String, String) -> Unit,
    val onToggleMerchantAlias: (MerchantAlias) -> Unit,
    val onDeleteMerchantAlias: (MerchantAlias) -> Unit,
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
    val activeLedgerId: String?,
)

@Composable
internal fun SettingsDestinationHost(
    state: SettingsUiState,
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

    val backgroundPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        runCatching {
            backgroundImageStore.copyPickedImageToPrivateStorage(uri)
        }
            .onSuccess { path -> route = SettingsDestination.BackgroundCrop(path) }
            .onFailure { actions.onBackgroundImageError("背景没有保存成功，请换一张图片再试。") }
    }

    fun launchImagePicker() {
        backgroundPickerLauncher.launch(
            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
        )
    }

    fun previewThemeDefault() {
        actions.onApplyBackgroundSettings(state.backgroundSettings.withoutBackground())
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
            state = state,
            showAdvancedTools = showAdvancedTools,
            onOpenServer = { route = SettingsDestination.Server },
            onOpenAppearance = { route = SettingsDestination.Appearance },
            onOpenDashboardCards = { route = SettingsDestination.DashboardCards },
            onOpenCategoryRules = { route = SettingsDestination.CategoryRules },
            onOpenMerchantAliases = { route = SettingsDestination.MerchantAliases },
            onOpenDataExport = { route = SettingsDestination.DataExport },
            onOpenNotifications = { route = SettingsDestination.NotificationPreferences },
            onOpenSecurity = { route = SettingsDestination.SecurityPrivacy },
            onOpenLedgers = { route = SettingsDestination.Ledgers },
            onOpenFamilyMembers = { route = SettingsDestination.FamilyMembers },
            onOpenJoinFamilyLedger = { route = SettingsDestination.JoinFamilyLedger },
            onOpenBillSplits = { route = SettingsDestination.BillSplits },
            onOpenBackgroundTasks = { route = SettingsDestination.BackgroundTasks },
            onOpenIncomePlans = { route = SettingsDestination.IncomePlans },
            onOpenAbout = { route = SettingsDestination.About },
        )

        SettingsDestination.Server -> ServerSettingsScreen(
            state = state,
            showAdvancedTools = showAdvancedTools,
            onBack = { route = SettingsDestination.Root },
            onTestConnection = actions.onTestConnection,
            onRunDiagnostics = actions.onRunDiagnostics,
            onRefreshServerSettings = actions.onRefreshServerSettings,
            onSync = actions.onSync,
        )

        SettingsDestination.Appearance -> AppearanceScreen(
            state = state,
            currentSkin = currentSkin,
            currentCurrency = currentCurrency,
            onBack = { route = SettingsDestination.Root },
            onSkinChange = actions.onSkinChange,
            onCurrencyChange = actions.onCurrencyChange,
            onOpenGallery = { route = SettingsDestination.BackgroundGallery },
            onPickCustomImage = ::launchImagePicker,
            onPreviewThemeDefault = ::previewThemeDefault,
            onClearBackgroundImage = {
                backgroundImageStore.deleteCustomBackground(state.backgroundSettings.customImagePath)
                actions.onClearBackgroundImage()
            },
            onImmersionModeChange = actions.onImmersionModeChange,
            onParallaxChange = actions.onParallaxChange,
            onReduceMotionChange = actions.onReduceMotionChange,
        )

        SettingsDestination.BackgroundGallery -> BackgroundGalleryScreen(
            currentSettings = state.backgroundSettings,
            onBack = { route = SettingsDestination.Appearance },
            onPickCustomImage = ::launchImagePicker,
            onPreviewThemeDefault = ::previewThemeDefault,
            onPreviewBuiltIn = { background ->
                route = SettingsDestination.BackgroundPreview(
                    settings = state.backgroundSettings.withBuiltInBackground(background.id),
                    title = background.name,
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
                            settings = state.backgroundSettings
                                .withCustomImage(croppedPath)
                                .copy(cropMode = cropMode),
                            title = "自定义背景",
                        )
                    }
                    .onFailure { actions.onBackgroundImageError("背景裁剪没有完成，请换一张图片再试。") }
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

        SettingsDestination.DashboardCards -> DashboardCardsScreen(
            repository = repositories.reportsRepository,
            readOnly = !ledgerRoleCanModify(state.role),
            onBack = { route = SettingsDestination.Root },
            onSaved = actions.onDashboardCardsChanged,
        )

        SettingsDestination.CategoryRules -> CategoryRulesScreen(
            rules = state.categoryRules,
            busy = state.busy,
            readOnly = !ledgerRoleCanModify(state.role),
            onBack = { route = SettingsDestination.Root },
            onCreateRule = actions.onCreateRule,
            onUpdateRule = actions.onUpdateRule,
            onToggleRule = actions.onToggleRule,
            onDeleteRule = actions.onDeleteRule,
            applications = state.ruleApplications,
            confirmedPreview = state.confirmedRulesPreview,
            onPreviewApplyConfirmedRules = actions.onPreviewApplyConfirmedRules,
            onConfirmApplyConfirmedRules = actions.onConfirmApplyConfirmedRules,
            onRollbackRuleApplication = actions.onRollbackRuleApplication,
        )

        SettingsDestination.MerchantAliases -> MerchantAliasesScreen(
            aliases = state.merchantAliases,
            busy = state.busy,
            readOnly = !ledgerRoleCanModify(state.role),
            message = state.message,
            onBack = { route = SettingsDestination.Root },
            onCreateAlias = actions.onCreateMerchantAlias,
            onToggleAlias = actions.onToggleMerchantAlias,
            onDeleteAlias = actions.onDeleteMerchantAlias,
        )

        SettingsDestination.DataExport -> DataExportScreen(
            state = state,
            onBack = { route = SettingsDestination.Root },
            onSync = actions.onSync,
            onClearCache = actions.onClearCache,
        )

        SettingsDestination.NotificationPreferences -> NotificationPreferencesScreen(
            preferences = state.notificationPreferences,
            readOnly = !ledgerRoleCanModify(state.role),
            onBack = { route = SettingsDestination.Root },
            onSave = actions.onSaveNotificationPreferences,
        )

        SettingsDestination.SecurityPrivacy -> SecurityPrivacyScreen(
            onBack = { route = SettingsDestination.Root },
            onClearCache = actions.onClearCache,
            onBindingCleared = actions.onBindingCleared,
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
                currentRole = state.role,
                onBack = { route = SettingsDestination.Root },
                onMembershipChanged = actions.onBindingChanged,
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

        SettingsDestination.IncomePlans -> {
            val vm: IncomePlanViewModel = viewModel(
                key = "income-plans",
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
