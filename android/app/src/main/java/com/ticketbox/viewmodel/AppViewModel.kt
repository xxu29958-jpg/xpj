package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ServerBindingRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
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
    val currency: CurrencyCode = CurrencyCode.Default,
    val currencyDisplay: CurrencyDisplay = CurrencyDisplay.Base,
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
    private val initialCurrency = CurrencyCode.fromStorageKey(settingsStore.currencyCodeKey())
    private val _uiState = MutableStateFlow(
        AppUiState(
            isBound = hasActiveBinding,
            unlocked = hasActiveBinding && (!requireLocalUnlock || !settingsStore.requiresUnlock()),
            skin = initialSkin,
            currency = initialCurrency,
            currencyDisplay = CurrencyDisplay.Base,
        ),
    )
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            settingsStore.backgroundSettingsFlow.collect { settings ->
                _uiState.update { it.copy(backgroundSettings = settings) }
            }
        }
        viewModelScope.launch {
            settingsStore.observeCurrencyCodeKey().collect { key ->
                val resolved = CurrencyCode.fromStorageKey(key)
                _uiState.update { state ->
                    if (state.currency == resolved) {
                        state
                    } else {
                        state.copy(
                            currency = resolved,
                            currencyDisplay = CurrencyDisplay.Base,
                        )
                    }
                }
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

    fun selectCurrency(currency: CurrencyCode) {
        settingsStore.saveCurrencyCodeKey(currency.storageKey)
        _uiState.update {
            it.copy(
                currency = currency,
                currencyDisplay = CurrencyDisplay.Base,
                authMessage = "已切换为${currency.displayName}默认记账币种",
            )
        }
    }

    fun clearBinding() {
        val currentSkin = _uiState.value.skin
        val currentCurrency = _uiState.value.currency
        val currentBackground = _uiState.value.backgroundSettings
        viewModelScope.launch {
            repository.clearBinding()
            settingsStore.saveAppSkinKey(currentSkin.storageKey)
            settingsStore.saveCurrencyCodeKey(currentCurrency.storageKey)
            _uiState.update {
                AppUiState(
                    skin = currentSkin,
                    currency = currentCurrency,
                    currencyDisplay = CurrencyDisplay.Base,
                    backgroundSettings = currentBackground,
                )
            }
        }
    }
}

internal const val BIND_RESTORE_FAILED_MESSAGE = "已绑定，但历史账本恢复失败，可稍后在账本页更新。"
