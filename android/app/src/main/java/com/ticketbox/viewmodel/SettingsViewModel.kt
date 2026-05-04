package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
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
    val lastConfirmedSyncAt: String? = null,
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
            lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
        ),
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadCategoryRules()
        loadServerSettings()
    }

    fun testConnection() {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            repository.testConnection()
                .onSuccess { _uiState.update { it.copy(busy = false, message = "连接正常") } }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "连接失败") } }
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
                            message = "同步完成",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "同步失败") } }
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
                            message = error.message ?: "连接检测失败",
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
                        it.copy(serverSettings = settings, busy = if (showBusy) false else it.busy)
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            busy = if (showBusy) false else it.busy,
                            message = error.message ?: "服务器设置加载失败",
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
                    message = "本地缓存已清除",
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
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "分类规则加载失败") } }
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
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "添加失败") } }
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
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "更新失败") } }
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
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "更新失败") } }
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
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "删除失败") } }
        }
    }
}
