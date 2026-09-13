package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.SettingsActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.UiText
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
    val access: LedgerAccessContext? = null,
    val serverUrl: String? = null,
    val accountName: String? = null,
    val ledgerName: String? = null,
    val deviceName: String? = null,
    val role: String? = null,
    val boundAt: String? = null,
    val notificationPreferences: NotificationPreferences = NotificationPreferences(),
    val serverSettings: ServerSettings? = null,
    val serverSettingsFresh: Boolean = false,
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
    private val repository: SettingsActions,
    private val settingsStore: TicketboxSettingsStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(SettingsUiState().withLocalBindingFields(repository, settingsStore))
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()
    private var connectionJob: Job? = null

    init {
        viewModelScope.launch { repository.observeAccess().collect { refreshLocalBindingState() } }
        loadServerSettings()
    }


    fun refreshLocalBindingState() {
        val access = repository.currentAccess()
        if (_uiState.value.access?.binding != access?.binding) {
            connectionJob?.cancel()
            _uiState.value = SettingsUiState().withLocalBindingFields(repository, settingsStore, access)
        } else {
            _uiState.update { it.withLocalBindingFields(repository, settingsStore, access) }
        }
    }

    private fun updateFor(binding: LogicalSessionBinding, transform: (SettingsUiState) -> SettingsUiState) {
        refreshLocalBindingState()
        if (_uiState.value.access?.binding == binding) _uiState.update(transform)
    }

    /** One cancellable connection operation; replacing a binding retires its pending result. */
    private fun launchBound(showBusy: Boolean = true, block: suspend (LogicalSessionBinding) -> Unit) {
        refreshLocalBindingState()
        val binding = _uiState.value.access?.binding ?: return
        if (_uiState.value.busy) return
        connectionJob?.cancel()
        if (showBusy) {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
        }
        connectionJob = viewModelScope.launch {
            refreshLocalBindingState()
            if (_uiState.value.access?.binding == binding) block(binding)
        }
    }

    fun sync() = launchBound { binding ->
        val synced = repository.syncConfirmed(month = null, category = null, tag = null)
        refreshLocalBindingState()
        if (_uiState.value.access?.binding != binding) return@launchBound
        if (synced.isFailure) {
            updateFor(binding) {
                it.copy(
                    busy = false,
                    message = requireNotNull(synced.exceptionOrNull()).toUiText(R.string.settings_vm_sync_failed),
                    messageTone = MessageTone.Danger,
                )
            }
            return@launchBound
        }
        val settings = repository.serverSettings()
        updateFor(binding) {
            it.withLocalBindingFields(repository, settingsStore).copy(
                busy = false,
                serverSettings = settings.getOrNull(),
                serverSettingsFresh = settings.isSuccess,
                message = UiText.res(
                    if (settings.isSuccess) R.string.settings_vm_sync_done
                    else R.string.settings_vm_sync_state_unavailable,
                ),
                messageTone = if (settings.isSuccess) MessageTone.Success else MessageTone.Info,
            )
        }
    }

    fun runDiagnostics() = launchBound { binding ->
        updateFor(binding) { it.copy(diagnostics = null) }
        repository.runConnectionDiagnostics(binding)
            .onSuccess { diagnostics ->
                val serverReadFailed = diagnostics.checks.any {
                    it.status == DiagnosticStatus.Fail && it.kind in setOf(DiagnosticCheckKind.Auth, DiagnosticCheckKind.ServerSettings)
                }
                updateFor(binding) {
                    it.copy(
                        busy = false,
                        diagnostics = diagnostics,
                        serverSettingsFresh = it.serverSettingsFresh && !serverReadFailed,
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
                updateFor(binding) {
                    it.copy(
                        busy = false,
                        serverSettingsFresh = false,
                        message = error.toUiText(R.string.settings_vm_diagnostics_incomplete),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }

    fun refreshServerSettings() = loadServerSettings(showBusy = true)

    fun cancelConnectionWork() {
        connectionJob?.cancel()
        _uiState.update { it.copy(busy = false, message = null, messageTone = MessageTone.Neutral) }
    }

    private fun loadServerSettings(showBusy: Boolean = false) = launchBound(showBusy) { binding ->
        repository.serverSettings()
            .onSuccess { settings ->
                updateFor(binding) {
                    it.withLocalBindingFields(repository, settingsStore).copy(
                        serverSettings = settings,
                        serverSettingsFresh = true,
                        accountName = settings.accountName,
                        ledgerName = settings.ledgerName,
                        deviceName = settings.deviceName,
                        role = settings.role,
                        lastUploadAt = settings.latestUploadAt,
                        message = null,
                        messageTone = MessageTone.Neutral,
                        busy = false,
                    )
                }
            }
            .onFailure { error ->
                updateFor(binding) {
                    it.copy(
                        busy = false,
                        serverSettingsFresh = false,
                        message = error.toUiText(R.string.settings_vm_server_settings_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }

    fun clearLocalCache() = launchBound { binding ->
        runCatching { repository.clearLocalCache() }
            .onSuccess {
                updateFor(binding) {
                    it.copy(
                        busy = false,
                        lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
                        message = UiText.res(R.string.settings_vm_cache_cleared),
                        messageTone = MessageTone.Success,
                    )
                }
            }
            .onFailure { error ->
                if (error is CancellationException) throw error
                updateFor(binding) {
                    it.copy(
                        busy = false,
                        message = error.toUiText(R.string.settings_vm_cache_clear_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }

    fun saveNotificationPreferences(preferences: NotificationPreferences) {
        refreshLocalBindingState()
        val savedPreferences = if (repository.currentAccess()?.canModify == true) {
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
                messageTone = if (downgraded) MessageTone.Info else MessageTone.Success,
            )
        }
    }
}

private fun SettingsUiState.withLocalBindingFields(
    repository: SettingsActions,
    settingsStore: TicketboxSettingsStore,
    access: LedgerAccessContext? = repository.currentAccess(),
): SettingsUiState {
    val binding = repository.localBinding()
    return copy(
        access = access,
        serverUrl = binding?.serverUrl,
        accountName = binding?.accountName,
        ledgerName = binding?.ledgerName,
        deviceName = binding?.deviceName,
        role = binding?.role,
        boundAt = binding?.boundAt,
        serverSettings = serverSettings?.let { settings ->
            binding?.role?.let { settings.copy(role = it) } ?: settings
        },
        notificationPreferences = settingsStore.notificationPreferences(),
        lastUploadAt = repository.lastUploadAt(),
        lastConfirmedSyncAt = repository.lastConfirmedSyncAt(),
    )
}
