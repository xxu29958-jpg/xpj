package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.SettingsScreen
import com.ticketbox.viewmodel.SettingsViewModel

@Composable
internal fun SettingsRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    val settingsViewModel: SettingsViewModel = viewModel(
        factory = screenFactory.settingsViewModelFactory,
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
        onSaveNotificationPreferences = settingsViewModel::saveNotificationPreferences,
        onCreateRule = settingsViewModel::createCategoryRule,
        onUpdateRule = settingsViewModel::updateCategoryRule,
        onToggleRule = settingsViewModel::toggleCategoryRule,
        onDeleteRule = settingsViewModel::deleteCategoryRule,
        onCreateMerchantAlias = settingsViewModel::createMerchantAlias,
        onToggleMerchantAlias = settingsViewModel::toggleMerchantAlias,
        onDeleteMerchantAlias = settingsViewModel::deleteMerchantAlias,
        onPreviewApplyConfirmedRules = settingsViewModel::previewApplyConfirmedRules,
        onConfirmApplyConfirmedRules = settingsViewModel::confirmApplyConfirmedRules,
        onRollbackRuleApplication = settingsViewModel::rollbackRuleApplication,
        onSkinChange = onSkinChange,
        onApplyBackgroundSettings = settingsViewModel::applyBackgroundSettings,
        onClearBackgroundImage = settingsViewModel::clearBackgroundImage,
        onBackgroundImageError = settingsViewModel::backgroundImageCopyFailed,
        onImmersionModeChange = settingsViewModel::setImmersionMode,
        onParallaxChange = settingsViewModel::setParallaxEnabled,
        onReduceMotionChange = settingsViewModel::setReduceMotion,
        onBindingCleared = onBindingCleared,
        showAdvancedTools = BuildConfig.SHOW_ADVANCED_TOOLS,
        ledgerRepository = screenFactory.ledgerRepository,
        reportsRepository = screenFactory.reportsRepository,
        activeLedgerId = screenFactory.ledgerRepository.activeLedgerId(),
        onBindingChanged = settingsViewModel::refreshLocalBindingState,
        onLedgerSwitched = settingsViewModel::sync,
        onDashboardCardsChanged = shellState::markDashboardCardsChanged,
    )
}
