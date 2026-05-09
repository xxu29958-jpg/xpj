package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.ServerSettings
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val serverUrl: String? = null,
    val monthlyBudgetCents: Long? = null,
    val serverSettings: ServerSettings? = null,
    val diagnostics: ConnectionDiagnostics? = null,
    val categoryRules: List<CategoryRule> = emptyList(),
    val lastUploadAt: String? = null,
    val lastConfirmedSyncAt: String? = null,
    val backgroundSettings: BackgroundSettings = BackgroundSettings(),
    val busy: Boolean = false,
    val message: String? = null,
)

class SettingsViewModel(
    private val repository: ExpenseRepository,
    private val settingsStore: LocalSettingsStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        SettingsUiState(
            serverUrl = settingsStore.serverUrl(),
            monthlyBudgetCents = settingsStore.monthlyBudgetCents(),
            lastUploadAt = repository.lastUploadAt(),
            lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
        ),
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadCategoryRules()
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
            _uiState.update { it.copy(busy = true, message = null) }
            repository.syncConfirmed()
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            busy = false,
                            lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
                            message = "更新完成",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "暂时更新不了，请稍后再试。") } }
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
            if (showBusy) {
                _uiState.update { it.copy(busy = true, message = null) }
            }
            repository.serverSettings()
                .onSuccess { settings ->
                    _uiState.update {
                        it.copy(
                            serverSettings = settings,
                            lastUploadAt = repository.lastUploadAt() ?: settings.latestUploadAt,
                            message = null,
                            busy = if (showBusy) false else it.busy,
                        )
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

    fun loadCategoryRules() {
        viewModelScope.launch {
            repository.categoryRules()
                .onSuccess { rules -> _uiState.update { it.copy(categoryRules = rules) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "分类规则暂时打不开。") } }
        }
    }

    fun createCategoryRule(keyword: String, category: String, priority: Int) {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            repository.createCategoryRule(keyword = keyword, category = category, priority = priority)
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
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            repository.updateCategoryRule(
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
        viewModelScope.launch {
            repository.updateCategoryRule(rule.id, enabled = !rule.enabled)
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
        viewModelScope.launch {
            repository.deleteCategoryRule(rule.id)
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
