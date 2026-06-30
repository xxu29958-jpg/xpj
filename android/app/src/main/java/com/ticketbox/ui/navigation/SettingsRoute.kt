package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.viewmodel.AppearanceViewModel
import com.ticketbox.viewmodel.CategoryRulesViewModel
import com.ticketbox.viewmodel.MerchantAliasViewModel
import com.ticketbox.viewmodel.SettingsViewModel

@Composable
internal fun SettingsRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    currentCurrency: CurrencyCode,
    onSkinChange: (AppSkin) -> Unit,
    onCurrencyChange: (CurrencyCode) -> Unit,
    onBindingCleared: () -> Unit,
) {
    val settingsViewModel: SettingsViewModel = viewModel(
        factory = screenFactory.settingsViewModelFactory,
    )
    val categoryRulesViewModel: CategoryRulesViewModel = viewModel(
        factory = screenFactory.categoryRulesViewModelFactory,
    )
    val merchantAliasViewModel: MerchantAliasViewModel = viewModel(
        factory = screenFactory.merchantAliasViewModelFactory,
    )
    val appearanceViewModel: AppearanceViewModel = viewModel(
        factory = screenFactory.appearanceViewModelFactory,
    )

    val settingsState by settingsViewModel.uiState.collectAsStateWithLifecycle()
    val rulesState by categoryRulesViewModel.uiState.collectAsStateWithLifecycle()
    val merchantState by merchantAliasViewModel.uiState.collectAsStateWithLifecycle()
    val appearanceState by appearanceViewModel.uiState.collectAsStateWithLifecycle()

    SettingsDestinationHost(
        states = SettingsRouteStates(
            settings = settingsState,
            rules = rulesState,
            merchant = merchantState,
            appearance = appearanceState,
        ),
        currentSkin = currentSkin,
        currentCurrency = currentCurrency,
        showAdvancedTools = BuildConfig.SHOW_ADVANCED_TOOLS,
        actions = SettingsRouteActions(
            onTestConnection = settingsViewModel::testConnection,
            onRunDiagnostics = settingsViewModel::runDiagnostics,
            onRefreshServerSettings = settingsViewModel::refreshServerSettings,
            onSync = settingsViewModel::sync,
            onClearCache = settingsViewModel::clearLocalCache,
            onSaveNotificationPreferences = settingsViewModel::saveNotificationPreferences,
            onCreateRule = categoryRulesViewModel::createCategoryRule,
            onUpdateRule = categoryRulesViewModel::updateCategoryRule,
            onToggleRule = categoryRulesViewModel::toggleCategoryRule,
            onDeleteRule = categoryRulesViewModel::deleteCategoryRule,
            onUndoRuleDelete = categoryRulesViewModel::undoDelete,
            onDismissRuleUndo = categoryRulesViewModel::dismissUndo,
            onCreateMerchantCatalog = merchantAliasViewModel::createMerchantCatalog,
            onRenameMerchantCatalog = merchantAliasViewModel::renameMerchantCatalog,
            onToggleMerchantCatalog = merchantAliasViewModel::toggleMerchantCatalog,
            onMergeMerchantCatalog = merchantAliasViewModel::mergeMerchantCatalog,
            onDeleteMerchantCatalog = merchantAliasViewModel::deleteMerchantCatalog,
            onCreateMerchantAlias = merchantAliasViewModel::createMerchantAlias,
            onToggleMerchantAlias = merchantAliasViewModel::toggleMerchantAlias,
            onDeleteMerchantAlias = merchantAliasViewModel::deleteMerchantAlias,
            onUndoMerchantAlias = merchantAliasViewModel::undoDelete,
            onDismissMerchantAliasUndo = merchantAliasViewModel::dismissUndo,
            onDismissMerchantCatalogMergeSuggestion = merchantAliasViewModel::consumeMergeSuggestion,
            onPreviewApplyConfirmedRules = categoryRulesViewModel::previewApplyConfirmedRules,
            onConfirmApplyConfirmedRules = categoryRulesViewModel::confirmApplyConfirmedRules,
            onRollbackRuleApplication = categoryRulesViewModel::rollbackRuleApplication,
            onSkinChange = onSkinChange,
            onCurrencyChange = onCurrencyChange,
            onApplyBackgroundSettings = appearanceViewModel::applyBackgroundSettings,
            onClearBackgroundImage = appearanceViewModel::clearBackgroundImage,
            onBackgroundImageError = appearanceViewModel::backgroundImageCopyFailed,
            onImmersionModeChange = appearanceViewModel::setImmersionMode,
            onParallaxChange = appearanceViewModel::setParallaxEnabled,
            onReduceMotionChange = appearanceViewModel::setReduceMotion,
            onBindingCleared = onBindingCleared,
            onBindingChanged = settingsViewModel::refreshLocalBindingState,
            onLedgerSwitched = settingsViewModel::sync,
            onDashboardCardsChanged = shellState::markDashboardCardsChanged,
        ),
        repositories = SettingsRouteRepositories(
            ledgerRepository = screenFactory.ledgerRepository,
            expenseRepository = screenFactory.repository,
            reportsRepository = screenFactory.reportsRepository,
            incomePlanRepository = screenFactory.incomePlanRepository,
            outboxRepository = screenFactory.outboxRepository,
            tagRepository = screenFactory.tagRepository,
            activeLedgerId = screenFactory.ledgerRepository.activeLedgerId(),
        ),
    )
}
