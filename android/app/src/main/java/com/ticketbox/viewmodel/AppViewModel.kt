package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SecureTokenStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AppUiState(
    val isBound: Boolean = false,
    val unlocked: Boolean = false,
    val binding: Boolean = false,
    val skin: AppSkin = AppSkin.Default,
    val backgroundSettings: BackgroundSettings = BackgroundSettings(),
    val authMessage: String? = null,
)

class AppViewModel(
    private val repository: ExpenseRepository,
    private val settingsStore: LocalSettingsStore,
    private val tokenStore: SecureTokenStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        AppUiState(
            isBound = settingsStore.isBound() && tokenStore.getToken() != null,
            unlocked = settingsStore.isBound() && tokenStore.getToken() != null && !settingsStore.requiresUnlock(),
            skin = AppSkin.fromStorageKey(settingsStore.appSkinKey()),
        ),
    )
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            settingsStore.backgroundSettingsFlow.collect { settings ->
                _uiState.update { it.copy(backgroundSettings = settings) }
            }
        }
    }

    fun bind(serverUrl: String, pairingCode: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(binding = true, authMessage = null) }
            repository.bindServer(serverUrl, pairingCode)
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(isBound = true, unlocked = true, binding = false, authMessage = null)
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(binding = false, authMessage = error.message ?: "绑定没成功，请检查账本地址和绑定码。") }
                }
        }
    }

    fun markBackgrounded() {
        settingsStore.markBackgrounded()
    }

    fun refreshUnlockRequirement() {
        if (_uiState.value.isBound && settingsStore.requiresUnlock()) {
            _uiState.update { it.copy(unlocked = false) }
        }
    }

    fun unlockSucceeded() {
        settingsStore.markUnlocked()
        _uiState.update { it.copy(unlocked = true, authMessage = null) }
    }

    fun unlockFailed(message: String) {
        _uiState.update { it.copy(authMessage = message) }
    }

    fun selectSkin(skin: AppSkin) {
        settingsStore.saveAppSkinKey(skin.storageKey)
        _uiState.update { it.copy(skin = skin, authMessage = "已切换为${skin.displayName}") }
    }

    fun clearBinding() {
        val currentSkin = _uiState.value.skin
        val currentBackground = _uiState.value.backgroundSettings
        viewModelScope.launch {
            repository.clearBinding()
            settingsStore.saveAppSkinKey(currentSkin.storageKey)
            _uiState.update {
                AppUiState(
                    skin = currentSkin,
                    backgroundSettings = currentBackground,
                )
            }
        }
    }
}
