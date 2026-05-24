package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.SettingsScreen
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

    val mergedState = settingsState.copy(
        categoryRules = rulesState.categoryRules,
        ruleApplications = rulesState.ruleApplications,
        confirmedRulesPreview = rulesState.confirmedRulesPreview,
        merchantAliases = merchantState.merchantAliases,
        backgroundSettings = appearanceState.backgroundSettings,
        busy = settingsState.busy || rulesState.busy || merchantState.busy,
        message = settingsState.message
            ?: rulesState.message
            ?: merchantState.message
            ?: appearanceState.message,
    )

    SettingsScreen(
        state = mergedState,
        currentSkin = currentSkin,
        currentCurrency = currentCurrency,
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
        onCreateMerchantAlias = merchantAliasViewModel::createMerchantAlias,
        onToggleMerchantAlias = merchantAliasViewModel::toggleMerchantAlias,
        onDeleteMerchantAlias = merchantAliasViewModel::deleteMerchantAlias,
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
        showAdvancedTools = BuildConfig.SHOW_ADVANCED_TOOLS,
        ledgerRepository = screenFactory.ledgerRepository,
        expenseRepository = screenFactory.repository,
        reportsRepository = screenFactory.reportsRepository,
        incomePlanRepository = screenFactory.incomePlanRepository,
        activeLedgerId = screenFactory.ledgerRepository.activeLedgerId(),
        onBindingChanged = settingsViewModel::refreshLocalBindingState,
        onLedgerSwitched = settingsViewModel::sync,
        onDashboardCardsChanged = shellState::markDashboardCardsChanged,
    )
}
