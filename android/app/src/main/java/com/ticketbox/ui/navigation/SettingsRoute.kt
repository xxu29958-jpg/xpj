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

internal data class SettingsPreferenceControls(
    val currentSkin: AppSkin,
    val currentCurrency: CurrencyCode,
    val onSkinChange: (AppSkin) -> Unit,
    val onCurrencyChange: (CurrencyCode) -> Unit,
)

/**
 * 账户与设置（workspace）路由。218-B1：拆账 / 收入计划 / 首页卡片已迁出设置页
 * （前两者在一级域二级页，后者随 Today 域一并删除）；分类规则 / 商家别名 / 标签 /
 * 回收站属后续 TransactionsLibrary slice，暂留设置页。
 */
@Composable
internal fun SettingsRoute(
    screenFactory: MainScreenFactory,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
    onClose: () -> Unit,
    onTransactionVocabularyChanged: () -> Unit = {},
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
            onTransactionVocabularyChanged = onTransactionVocabularyChanged,
        ),
        repositories = SettingsRouteRepositories(
            ledgerRepository = screenFactory.ledgerRepository,
            expenseRepository = screenFactory.repository,
            outboxRepository = screenFactory.outboxRepository,
            tagRepository = screenFactory.tagRepository,
            activeLedgerId = screenFactory.ledgerRepository.activeLedgerId(),
        ),
    )
}
