package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ServerBindingRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
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
    private val repository: ServerBindingRepository,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val requireLocalUnlock: Boolean = BuildConfig.REQUIRE_LOCAL_UNLOCK,
) : ViewModel() {
    private val hasActiveBinding: Boolean
        get() = settingsStore.isBound() && tokenStore.getToken() != null

    private val initialSkin = normalizedInitialSkin()
    private val _uiState = MutableStateFlow(
        AppUiState(
            isBound = hasActiveBinding,
            unlocked = hasActiveBinding && (!requireLocalUnlock || !settingsStore.requiresUnlock()),
            skin = initialSkin,
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

    private fun normalizedInitialSkin(): AppSkin {
        val rawKey = settingsStore.appSkinKey()
        val skin = AppSkin.fromStorageKey(rawKey)
        if (rawKey != skin.storageKey) {
            settingsStore.saveAppSkinKey(skin.storageKey)
        }
        return skin
    }

    fun bind(serverUrl: String, pairingCode: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(binding = true, authMessage = null) }
            repository.bindServer(serverUrl, pairingCode)
                .onSuccess { result ->
                    _uiState.update { state ->
                        state.copy(
                            isBound = true,
                            unlocked = true,
                            binding = false,
                            authMessage = if (result.confirmedRestoreFailed) BIND_RESTORE_FAILED_MESSAGE else null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(binding = false, authMessage = error.message ?: "绑定没成功，请检查账本地址和绑定码。") }
                }
        }
    }

    fun markBackgrounded() {
        if (!requireLocalUnlock) return
        settingsStore.markBackgrounded()
    }

    fun refreshUnlockRequirement() {
        if (!_uiState.value.isBound) return
        if (!requireLocalUnlock) {
            _uiState.update { it.copy(unlocked = true) }
            return
        }
        if (settingsStore.requiresUnlock()) {
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

    fun consumeAuthMessage() {
        _uiState.update { it.copy(authMessage = null) }
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

internal const val BIND_RESTORE_FAILED_MESSAGE = "已绑定，但历史账本恢复失败，可稍后在账本页更新。"
