package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val serverUrl: String? = null,
    val accountName: String? = null,
    val ledgerName: String? = null,
    val deviceName: String? = null,
    val role: String? = null,
    val boundAt: String? = null,
    val monthlyBudgetCents: Long? = null,
    val notificationPreferences: NotificationPreferences = NotificationPreferences(),
    val serverSettings: ServerSettings? = null,
    val diagnostics: ConnectionDiagnostics? = null,
    val categoryRules: List<CategoryRule> = emptyList(),
    val merchantAliases: List<MerchantAlias> = emptyList(),
    val ruleApplications: List<RuleApplicationBatch> = emptyList(),
    val confirmedRulesPreview: RuleApplyConfirmedResult? = null,
    val lastUploadAt: String? = null,
    val lastConfirmedSyncAt: String? = null,
    val backgroundSettings: BackgroundSettings = BackgroundSettings(),
    val busy: Boolean = false,
    val message: String? = null,
)

class SettingsViewModel(
    private val repository: ExpenseRepository,
    private val ruleRepository: RuleRepository,
    private val merchantRepository: MerchantRepository,
    private val settingsStore: TicketboxSettingsStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(SettingsUiState().withLocalBindingFields())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadCategoryRules()
        loadMerchantAliases()
        loadRuleApplications()
        loadServerSettings()
        observeBackgroundSettings()
    }

    private fun observeBackgroundSettings() {
        viewModelScope.launch {
            settingsStore.backgroundSettingsFlow.collect { settings ->
                _uiState.update { it.copy(backgroundSettings = settings) }
            }
        }
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(_uiState.value.role ?: repository.currentLedgerRole())
    }

    private fun SettingsUiState.withLocalBindingFields(
        busy: Boolean = this.busy,
        message: String? = this.message,
    ): SettingsUiState {
        val localAccountName = settingsStore.accountName()
        val localLedgerName = settingsStore.ledgerName()
        val localDeviceName = settingsStore.deviceName()
        val localRole = settingsStore.role()
        return copy(
            serverUrl = settingsStore.serverUrl(),
            accountName = localAccountName,
            ledgerName = localLedgerName,
            deviceName = localDeviceName,
            role = localRole,
            boundAt = settingsStore.boundAt(),
            monthlyBudgetCents = settingsStore.monthlyBudgetCents(),
            notificationPreferences = settingsStore.notificationPreferences(),
            serverSettings = serverSettings?.copy(
                accountName = localAccountName ?: serverSettings.accountName,
                ledgerName = localLedgerName ?: serverSettings.ledgerName,
                deviceName = localDeviceName ?: serverSettings.deviceName,
                role = localRole ?: serverSettings.role,
            ),
            lastUploadAt = repository.lastUploadAt(),
            lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
            busy = busy,
            message = message,
        )
    }

    fun refreshLocalBindingState() {
        _uiState.update { it.withLocalBindingFields() }
    }

    fun testConnection() {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            repository.testConnection()
                .onSuccess { _uiState.update { it.copy(busy = false, message = "连接正常") } }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "暂时连不上小票夹，请稍后再试。") } }
        }
    }

    fun sync() {
        viewModelScope.launch {
            _uiState.update { it.withLocalBindingFields(busy = true, message = null) }
            repository.syncConfirmed()
                .onSuccess {
                    _uiState.update {
                        it.withLocalBindingFields(
                            busy = false,
                            message = "更新完成",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.withLocalBindingFields(
                            busy = false,
                            message = error.message ?: "暂时更新不了，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun runDiagnostics() {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, diagnostics = null) }
            repository.runConnectionDiagnostics()
                .onSuccess { diagnostics ->
                    _uiState.update {
                        it.copy(
                            busy = false,
                            diagnostics = diagnostics,
                            message = if (diagnostics.isHealthy) {
                                "连接检测通过"
                            } else {
                                "连接检测发现 ${diagnostics.failedCount} 个问题"
                            },
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = error.message ?: "没有完成检测，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun refreshServerSettings() {
        loadServerSettings(showBusy = true)
    }

    private fun loadServerSettings(showBusy: Boolean = false) {
        viewModelScope.launch {
            val ledgerIdAtRequest = settingsStore.activeLedgerId()
            if (showBusy) {
                _uiState.update { it.copy(busy = true, message = null) }
            }
            repository.serverSettings()
                .onSuccess { settings ->
                    _uiState.update {
                        if (ledgerIdAtRequest != settingsStore.activeLedgerId()) {
                            it.withLocalBindingFields(
                                busy = if (showBusy) false else it.busy,
                                message = null,
                            )
                        } else {
                            it.copy(
                                serverSettings = settings,
                                accountName = settings.accountName,
                                ledgerName = settings.ledgerName,
                                deviceName = settings.deviceName,
                                role = settings.role,
                                lastUploadAt = repository.lastUploadAt() ?: settings.latestUploadAt,
                                message = null,
                                busy = if (showBusy) false else it.busy,
                            )
                        }
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            busy = if (showBusy) false else it.busy,
                            message = "账本状态暂时没有更新，稍后再试。",
                        )
                    }
                }
        }
    }

    fun clearLocalCache() {
        viewModelScope.launch {
            repository.clearLocalCache()
            _uiState.update {
                it.copy(
                    lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
                    message = "手机缓存已清除",
                )
            }
        }
    }

    fun saveMonthlyBudget(amountCents: Long?) {
        repository.saveMonthlyBudgetCents(amountCents)
        _uiState.update {
            it.copy(
                monthlyBudgetCents = amountCents?.takeIf { value -> value > 0L },
                message = if (amountCents == null || amountCents <= 0L) {
                    "月预算已关闭"
                } else {
                    "月预算已保存"
                },
            )
        }
    }

    fun saveNotificationPreferences(preferences: NotificationPreferences) {
        val savedPreferences = if (canModifyCurrentLedger()) {
            preferences
        } else {
            preferences.copy(autoCaptureEnabled = false)
        }
        settingsStore.saveNotificationPreferences(savedPreferences)
        _uiState.update {
            it.copy(
                notificationPreferences = savedPreferences,
                message = if (preferences.autoCaptureEnabled && !savedPreferences.autoCaptureEnabled) {
                    READ_ONLY_LEDGER_MESSAGE
                } else {
                    "通知偏好已保存"
                },
            )
        }
    }

    fun loadCategoryRules() {
        viewModelScope.launch {
            ruleRepository.categoryRules()
                .onSuccess { rules -> _uiState.update { it.copy(categoryRules = rules) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "分类规则暂时打不开。") } }
        }
    }

    fun loadMerchantAliases() {
        viewModelScope.launch {
            merchantRepository.merchantAliases()
                .onSuccess { aliases -> _uiState.update { it.copy(merchantAliases = aliases.sortedMerchantAliases()) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "商家别名暂时打不开。") } }
        }
    }

    fun loadRuleApplications() {
        viewModelScope.launch {
            ruleRepository.ruleApplications()
                .onSuccess { applications -> _uiState.update { it.copy(ruleApplications = applications) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "规则应用记录暂时打不开。") } }
        }
    }

    fun createCategoryRule(keyword: String, category: String, priority: Int) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.createCategoryRule(keyword = keyword, category = category, priority = priority)
                .onSuccess { rule ->
                    _uiState.update {
                        it.copy(
                            categoryRules = (it.categoryRules + rule).sortedWith(
                                compareByDescending<CategoryRule> { item -> item.enabled }
                                    .thenByDescending { item -> item.priority }
                                    .thenBy { item -> item.keyword },
                            ),
                            busy = false,
                            message = "分类规则已添加",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有添加成功，请稍后再试。") } }
        }
    }

    fun updateCategoryRule(rule: CategoryRule, keyword: String, category: String, priority: Int) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.updateCategoryRule(
                id = rule.id,
                keyword = keyword.trim(),
                category = category.trim(),
                priority = priority,
            )
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.map { if (it.id == updated.id) updated else it },
                            busy = false,
                            message = "分类规则已更新",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
        }
    }

    fun toggleCategoryRule(rule: CategoryRule) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            ruleRepository.updateCategoryRule(rule.id, enabled = !rule.enabled)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.map { if (it.id == updated.id) updated else it },
                            message = if (updated.enabled) "分类规则已启用" else "分类规则已停用",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有更新成功，请稍后再试。") } }
        }
    }

    fun deleteCategoryRule(rule: CategoryRule) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            ruleRepository.deleteCategoryRule(rule.id)
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.filterNot { it.id == rule.id },
                            message = "分类规则已删除",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有删除成功，请稍后再试。") } }
        }
    }

    fun createMerchantAlias(canonicalMerchant: String, alias: String) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            merchantRepository.createMerchantAlias(canonicalMerchant = canonicalMerchant, alias = alias)
                .onSuccess { created ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = (state.merchantAliases + created).sortedMerchantAliases(),
                            busy = false,
                            message = "商家别名已添加",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有添加成功，请稍后再试。") } }
        }
    }

    fun toggleMerchantAlias(alias: MerchantAlias) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            merchantRepository.updateMerchantAlias(alias.publicId, enabled = !alias.enabled)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases
                                .map { if (it.publicId == updated.publicId) updated else it }
                                .sortedMerchantAliases(),
                            message = if (updated.enabled) "商家别名已启用" else "商家别名已停用",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有更新成功，请稍后再试。") } }
        }
    }

    fun deleteMerchantAlias(alias: MerchantAlias) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            merchantRepository.deleteMerchantAlias(alias.publicId)
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases.filterNot { it.publicId == alias.publicId },
                            message = "商家别名已删除",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有删除成功，请稍后再试。") } }
        }
    }

    fun previewApplyConfirmedRules() {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.previewApplyConfirmedRules()
                .onSuccess { preview ->
                    _uiState.update {
                        it.copy(
                            confirmedRulesPreview = preview,
                            busy = false,
                            message = if (preview.changedCount == 0) {
                                "已确认账单暂无可更新分类。"
                            } else {
                                "找到 ${preview.changedCount} 笔可更新账单。"
                            },
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有完成预览，请稍后再试。") } }
        }
    }

    fun confirmApplyConfirmedRules() {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            val previewToken = _uiState.value.confirmedRulesPreview?.previewToken
            if (previewToken.isNullOrBlank()) {
                _uiState.update { it.copy(busy = false, message = "请先预览影响范围。") }
                return@launch
            }
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.confirmApplyConfirmedRules(previewToken)
                .onSuccess { result ->
                    ruleRepository.ruleApplications()
                        .onSuccess { applications ->
                            _uiState.update { it.copy(ruleApplications = applications) }
                        }
                    _uiState.update {
                        it.copy(
                            confirmedRulesPreview = result,
                            busy = false,
                            message = if (result.changedCount == 0) "没有账单需要更新。" else "已更新 ${result.changedCount} 笔账单分类。",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有应用成功，请稍后再试。") } }
        }
    }

    fun rollbackRuleApplication(application: RuleApplicationBatch) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(role = repository.currentLedgerRole(), busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.rollbackRuleApplication(application.publicId)
                .onSuccess { rollback ->
                    ruleRepository.ruleApplications()
                        .onSuccess { applications ->
                            _uiState.update { it.copy(ruleApplications = applications) }
                        }
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = "已回退 ${rollback.changed} 笔分类，跳过 ${rollback.skipped} 笔。",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有回退成功，请稍后再试。") } }
        }
    }

    fun saveBackgroundImage(path: String) {
        viewModelScope.launch {
            runCatching { settingsStore.saveBackgroundImagePath(path) }
                .onSuccess { _uiState.update { it.copy(message = "背景已更新") } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "背景没有保存成功。") } }
        }
    }

    fun applyBackgroundSettings(settings: BackgroundSettings) {
        viewModelScope.launch {
            runCatching { settingsStore.saveBackgroundSettings(settings) }
                .onSuccess { _uiState.update { it.copy(message = "背景已应用") } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "背景没有保存成功。") } }
        }
    }

    fun resetThemeBackground() {
        viewModelScope.launch {
            settingsStore.saveBackgroundSettings(_uiState.value.backgroundSettings.withoutBackground())
            _uiState.update { it.copy(message = "已恢复跟随主题背景") }
        }
    }

    fun clearBackgroundImage() {
        viewModelScope.launch {
            settingsStore.clearBackgroundImage()
            _uiState.update {
                it.copy(
                    backgroundSettings = it.backgroundSettings.withoutBackground(),
                    message = "已恢复跟随主题背景",
                )
            }
        }
    }

    fun setBackgroundCropMode(mode: BackgroundCropMode) {
        viewModelScope.launch {
            settingsStore.setBackgroundCropMode(mode)
            _uiState.update { it.copy(message = "构图已切换为${mode.displayName}") }
        }
    }

    fun setImmersionMode(mode: ImmersionMode) {
        viewModelScope.launch {
            settingsStore.setImmersionMode(mode)
            _uiState.update { it.copy(message = "已切换为${mode.displayName}模式") }
        }
    }

    fun setParallaxEnabled(enabled: Boolean) {
        viewModelScope.launch {
            settingsStore.setParallaxEnabled(enabled)
            _uiState.update { it.copy(message = if (enabled) "视差动效已开启" else "视差动效已关闭") }
        }
    }

    fun setReduceMotion(enabled: Boolean) {
        viewModelScope.launch {
            settingsStore.setReduceMotion(enabled)
            _uiState.update { it.copy(message = if (enabled) "已减少背景动效" else "已恢复轻微动效") }
        }
    }

    fun backgroundImageCopyFailed(message: String) {
        _uiState.update { it.copy(message = message) }
    }
}

private fun List<MerchantAlias>.sortedMerchantAliases(): List<MerchantAlias> =
    sortedWith(
        compareByDescending<MerchantAlias> { it.enabled }
            .thenBy { it.canonicalKey }
            .thenBy { it.aliasKey },
    )
