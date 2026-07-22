package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.viewmodel.AppearanceViewModel
import com.ticketbox.viewmodel.SettingsViewModel

internal data class SettingsPreferenceControls(
    val currentSkin: AppSkin,
    val currentCurrency: CurrencyCode,
    val onSkinChange: (AppSkin) -> Unit,
    val onCurrencyChange: (CurrencyCode) -> Unit,
)

@Composable
internal fun SettingsRoute(
    screenFactory: MainScreenFactory,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
    onClose: () -> Unit,
) {
    val settingsViewModel: SettingsViewModel = viewModel(
        factory = screenFactory.settingsViewModelFactory,
    )
    val appearanceViewModel: AppearanceViewModel = viewModel(
        factory = screenFactory.appearanceViewModelFactory,
    )

    val settingsState by settingsViewModel.uiState.collectAsStateWithLifecycle()
    val appearanceState by appearanceViewModel.uiState.collectAsStateWithLifecycle()

    SettingsDestinationHost(
        states = SettingsRouteStates(
            settings = settingsState,
            appearance = appearanceState,
        ),
        chromeState = SettingsDestinationChromeState(
            currentSkin = preferenceControls.currentSkin,
            currentCurrency = preferenceControls.currentCurrency,
            showAdvancedTools = BuildConfig.SHOW_ADVANCED_TOOLS,
        ),
        navigation = SettingsDestinationNavigation(onCloseRoot = onClose),
        actions = SettingsRouteActions(
            onTestConnection = settingsViewModel::testConnection,
            onRunDiagnostics = settingsViewModel::runDiagnostics,
            onRefreshServerSettings = settingsViewModel::refreshServerSettings,
            onSync = settingsViewModel::sync,
            onClearCache = settingsViewModel::clearLocalCache,
            onSaveNotificationPreferences = settingsViewModel::saveNotificationPreferences,
            onSkinChange = preferenceControls.onSkinChange,
            onCurrencyChange = preferenceControls.onCurrencyChange,
            onApplyBackgroundSettings = appearanceViewModel::applyBackgroundSettings,
            onClearBackgroundImage = appearanceViewModel::clearBackgroundImage,
            onBackgroundImageError = appearanceViewModel::backgroundImageCopyFailed,
            onImmersionModeChange = appearanceViewModel::setImmersionMode,
            onParallaxChange = appearanceViewModel::setParallaxEnabled,
            onReduceMotionChange = appearanceViewModel::setReduceMotion,
            onBindingCleared = onBindingCleared,
            onBindingChanged = settingsViewModel::refreshLocalBindingState,
            onLedgerSwitched = settingsViewModel::sync,
        ),
        repositories = SettingsRouteRepositories(
            ledgerRepository = screenFactory.ledgerRepository,
            expenseRepository = screenFactory.repository,
            outboxRepository = screenFactory.outboxRepository,
            activeLedgerId = screenFactory.ledgerRepository.activeLedgerId(),
        ),
    )
}
