package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * UI state for the connection / sync / diagnostics / notifications /
 * monthly-budget slice of the settings tree — the part SettingsViewModel
 * actually owns.
 *
 * Category-rule, merchant-alias and appearance state live in their own
 * ViewModels ([CategoryRulesViewModel], [MerchantAliasViewModel],
 * [AppearanceViewModel]); [com.ticketbox.ui.navigation.SettingsRoute] passes
 * each one to its own screen directly instead of merging them into this shape.
 * Each settings sub-screen therefore renders its own ViewModel's busy / message,
 * so status feedback no longer bleeds across sub-screens.
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
    val lastUploadAt: String? = null,
    val lastConfirmedSyncAt: String? = null,
    val busy: Boolean = false,
    val message: UiText? = null,
    // Tone of [message] for the page-header status banner (= /web .dt-alert
    // variant). Neutral while there is no message / it is cleared.
    val messageTone: MessageTone = MessageTone.Neutral,
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
        message: UiText? = this.message,
        messageTone: MessageTone = this.messageTone,
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
            messageTone = messageTone,
        )
    }

    fun refreshLocalBindingState() {
        _uiState.update { it.withLocalBindingFields() }
    }

    fun testConnection() {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            repository.testConnection()
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = UiText.res(R.string.settings_vm_connection_ok),
                            messageTone = MessageTone.Success,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = error.toUiText(R.string.settings_vm_connection_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun sync() {
        viewModelScope.launch {
            _uiState.update { it.withLocalBindingFields(busy = true, message = null, messageTone = MessageTone.Neutral) }
            repository.syncConfirmed()
                .onSuccess {
                    _uiState.update {
                        it.withLocalBindingFields(
                            busy = false,
                            message = UiText.res(R.string.settings_vm_sync_done),
                            messageTone = MessageTone.Success,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.withLocalBindingFields(
                            busy = false,
                            message = error.toUiText(R.string.settings_vm_sync_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun runDiagnostics() {
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral, diagnostics = null) }
            repository.runConnectionDiagnostics()
                .onSuccess { diagnostics ->
                    _uiState.update {
                        it.copy(
                            busy = false,
                            diagnostics = diagnostics,
                            message = if (diagnostics.isHealthy) {
                                UiText.res(R.string.settings_vm_diagnostics_passed)
                            } else {
                                UiText.res(R.string.settings_vm_diagnostics_failed_count, diagnostics.failedCount)
                            },
                            messageTone = if (diagnostics.isHealthy) MessageTone.Success else MessageTone.Danger,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = error.toUiText(R.string.settings_vm_diagnostics_incomplete),
                            messageTone = MessageTone.Danger,
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
                _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            }
            repository.serverSettings()
                .onSuccess { settings ->
                    _uiState.update {
                        if (ledgerIdAtRequest != settingsStore.activeLedgerId()) {
                            it.withLocalBindingFields(
                                busy = if (showBusy) false else it.busy,
                                message = null,
                                messageTone = MessageTone.Neutral,
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
                                messageTone = MessageTone.Neutral,
                                busy = if (showBusy) false else it.busy,
                            )
                        }
                    }
                }
                .onFailure {
                    _uiState.update {
                        it.copy(
                            busy = if (showBusy) false else it.busy,
                            message = UiText.res(R.string.settings_vm_server_settings_failed),
                            messageTone = MessageTone.Danger,
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
                    message = UiText.res(R.string.settings_vm_cache_cleared),
                    messageTone = MessageTone.Success,
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
                    UiText.res(R.string.settings_vm_monthly_budget_off)
                } else {
                    UiText.res(R.string.settings_vm_monthly_budget_saved)
                },
                messageTone = MessageTone.Success,
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
        val downgraded = preferences.autoCaptureEnabled && !savedPreferences.autoCaptureEnabled
        _uiState.update {
            it.copy(
                notificationPreferences = savedPreferences,
                message = if (downgraded) {
                    UiText.res(R.string.common_readonly_ledger)
                } else {
                    UiText.res(R.string.settings_vm_notifications_saved)
                },
                // A viewer-blocked auto-capture toggle is informational, not a success.
                messageTone = if (downgraded) MessageTone.Info else MessageTone.Success,
            )
        }
    }
}
