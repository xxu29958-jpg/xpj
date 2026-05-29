package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
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

/**
 * Composite UI state exposed to [com.ticketbox.ui.screens.SettingsScreen].
 *
 * SettingsViewModel owns the connection / sync / diagnostics / notifications /
 * monthly-budget slice. The category-rule, merchant-alias and appearance fields
 * are owned by their own ViewModels and merged into this shape at the Route
 * layer (see SettingsRoute). The data class keeps the full schema so the
 * screen contract stays stable.
 */
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
    // ADR-0038 undo: just-deleted rule surfaced as a 5s 撤销 affordance
    // (merged in from CategoryRulesViewModel by SettingsRoute).
    val categoryRuleUndoable: CategoryRule? = null,
    val merchantAliases: List<MerchantAlias> = emptyList(),
    // ADR-0038 undo: just-deleted alias surfaced as a 5s 撤销 affordance
    // (merged in from MerchantAliasViewModel by SettingsRoute).
    val merchantAliasUndoable: MerchantAlias? = null,
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
    private val settingsStore: TicketboxSettingsStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(SettingsUiState().withLocalBindingFields())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadServerSettings()
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
}
