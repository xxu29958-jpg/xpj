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
    /**
     * The local-unlock door was gracefully disabled because the device has no way to
     * satisfy it (no enrolled biometric and no usable lock-screen credential — audit
     * 8.1). The app is entered (the gate doesn't trap the user) and a persistent,
     * non-dismissable banner advises setting up a lock screen. Server-side auth is
     * unaffected (§5: the local door only unlocks local state).
     */
    val localUnlockDisabled: Boolean = false,
)

class AppViewModel(
    private val repository: ServerBindingRepository,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val requireLocalUnlock: Boolean = BuildConfig.REQUIRE_LOCAL_UNLOCK,
) : ViewModel() {
    private val hasActiveBinding: Boolean
        get() = settingsStore.isBound() && tokenStore.getToken() != null

    // Normalize the persisted skin key on construction: if the stored key isn't the
    // canonical form, rewrite it. Inlined into the initializer (not a helper method)
    // so the class stays within the detekt per-class function budget.
    private val initialSkin: AppSkin = run {
        val rawKey = settingsStore.appSkinKey()
        val skin = AppSkin.fromStorageKey(rawKey)
        if (rawKey != skin.storageKey) {
            settingsStore.saveAppSkinKey(skin.storageKey)
        }
        skin
    }
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
        // Device can't satisfy the local door (no biometric / no lock screen): the
        // door is gracefully disabled and must stay open — re-locking would re-trap
        // the user with no way out.
        if (_uiState.value.localUnlockDisabled) return
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

    /**
     * Gracefully disable the local-unlock door: the device has no enrolled biometric
     * and no lock-screen credential the prompt can use (audit 8.1 dead-end). Enter the
     * app (flip [AppUiState.unlocked]) and flag [AppUiState.localUnlockDisabled] so the
     * shell shows a persistent advisory banner. Clears any stale unlock error message.
     * Server-side auth is untouched (§5).
     */
    fun disableLocalUnlock() {
        _uiState.update { it.copy(unlocked = true, localUnlockDisabled = true, authMessage = null) }
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
