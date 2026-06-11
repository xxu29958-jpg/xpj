package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ServerBindingRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.UiText
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
    val authMessage: UiText? = null,
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
                    _uiState.update { it.copy(binding = false, authMessage = error.toUiText(R.string.app_bind_failed)) }
                }
        }
    }

    /**
     * Re-derive the bound flag after an out-of-band binding write — i.e. a
     * cold-start invitation join, where ``LedgerRepository.acceptInvitation``
     * (not [bind]) persisted the server URL + session token. Mirrors [bind]'s
     * success transition: a freshly persisted binding starts unlocked (the
     * session coordinator already ran ``markUnlocked`` for it). No-op while
     * nothing is actually persisted, so a spurious call can't fake a binding.
     */
    fun refreshBindingState() {
        if (!hasActiveBinding) return
        _uiState.update { it.copy(isBound = true, unlocked = true, authMessage = null) }
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

    fun unlockFailed(message: UiText) {
        _uiState.update { it.copy(authMessage = message) }
    }

    fun consumeAuthMessage() {
        _uiState.update { it.copy(authMessage = null) }
    }

    fun selectSkin(skin: AppSkin) {
        settingsStore.saveAppSkinKey(skin.storageKey)
        _uiState.update {
            it.copy(skin = skin, authMessage = UiText.res(R.string.app_skin_switched, skin.displayName))
        }
    }

    fun selectCurrency(currency: CurrencyCode) {
        settingsStore.saveCurrencyCodeKey(currency.storageKey)
        _uiState.update {
            it.copy(
                currency = currency,
                currencyDisplay = CurrencyDisplay.Base,
                authMessage = UiText.res(R.string.app_currency_switched, currency.displayName),
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

internal val BIND_RESTORE_FAILED_MESSAGE: UiText = UiText.res(R.string.app_bind_restore_failed)
