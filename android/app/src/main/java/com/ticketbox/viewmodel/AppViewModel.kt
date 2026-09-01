package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.BindServerResult
import com.ticketbox.data.repository.ServerBindingRepository
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class SessionVerificationState {
    Unbound,
    Verifying,
    Ready,
    Failed,
}

data class AppUiState(
    val isBound: Boolean = false,
    val unlocked: Boolean = false,
    val binding: Boolean = false,
    val sessionVerification: SessionVerificationState = SessionVerificationState.Unbound,
    val hasPendingEnrollment: Boolean = false,
    val themeMode: AppThemeMode = AppThemeMode.Default,
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
) {
    val isBusinessReady: Boolean
        get() = sessionVerification == SessionVerificationState.Ready
}

class AppViewModel(
    private val repository: ServerBindingRepository,
    private val settingsStore: TicketboxSettingsStore,
    private val requireLocalUnlock: Boolean = BuildConfig.REQUIRE_LOCAL_UNLOCK,
) : ViewModel() {
    private val hasActiveBinding: Boolean
        get() = repository.hasActiveSession()
    private val initialHasActiveBinding = hasActiveBinding
    private val initialBusinessSessionReady =
        initialHasActiveBinding && repository.isBusinessSessionReady()

    // Normalize the persisted theme-mode key on construction: if the stored key isn't
    // the canonical form, rewrite it. Inlined into the initializer (not a helper method)
    // so the class stays within the detekt per-class function budget.
    private val initialThemeMode: AppThemeMode = run {
        val rawKey = settingsStore.appThemeModeKey()
        val mode = AppThemeMode.fromStorageKey(rawKey)
        if (rawKey != mode.storageKey) {
            settingsStore.saveAppThemeModeKey(mode.storageKey)
        }
        mode
    }
    private val initialCurrency = CurrencyCode.fromStorageKey(settingsStore.currencyCodeKey())
    private val _uiState = MutableStateFlow(
        AppUiState(
            isBound = initialHasActiveBinding,
            unlocked = initialBusinessSessionReady &&
                (!requireLocalUnlock || !settingsStore.requiresUnlock()),
            sessionVerification = when {
                !initialHasActiveBinding -> SessionVerificationState.Unbound
                initialBusinessSessionReady -> SessionVerificationState.Ready
                else -> SessionVerificationState.Verifying
            },
            hasPendingEnrollment = repository.hasPendingBinding(),
            themeMode = initialThemeMode,
            currency = initialCurrency,
            currencyDisplay = CurrencyDisplay.Base,
        ),
    )
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()
    private var sessionVerificationInFlight = false

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
        if (initialHasActiveBinding && !initialBusinessSessionReady) {
            refreshBindingState()
        } else {
            if (!initialHasActiveBinding) {
                viewModelScope.launch {
                    _uiState.update { it.copy(binding = true, authMessage = null) }
                    val resumed = repository.resumePendingBinding()
                    if (resumed == null) {
                        _uiState.update {
                            it.copy(
                                binding = false,
                                hasPendingEnrollment = repository.hasPendingBinding(),
                            )
                        }
                    } else {
                        _uiState.finishBinding(
                            result = resumed,
                            hasPendingEnrollment = repository.hasPendingBinding(),
                        )
                    }
                }
            }
        }
    }

    fun bind(serverUrl: String, pairingCode: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(binding = true, authMessage = null) }
            _uiState.finishBinding(
                result = repository.bindServer(serverUrl, pairingCode),
                hasPendingEnrollment = repository.hasPendingBinding(),
            )
        }
    }

    /**
     * Re-derive the bound flag after an out-of-band binding write — i.e. a
     * cold-start invitation join, where ``LedgerRepository.acceptInvitation``
     * (not [bind]) persisted the server URL + session token. Mirrors [bind]'s
     * success transition: a freshly persisted, fully identified binding starts
     * unlocked. Legacy projections that still lack stable authority instead
     * enter reconciliation and stay outside the business surface until the
     * repository proves the upgraded session.
     */
    fun refreshBindingState() {
        if (!hasActiveBinding) {
            _uiState.markSessionUnbound()
            return
        }
        if (repository.isBusinessSessionReady()) {
            _uiState.markSessionReady(unlocked = true)
            return
        }
        if (sessionVerificationInFlight) return
        sessionVerificationInFlight = true
        _uiState.markSessionVerifying()
        viewModelScope.launch {
            try {
                val result = repository.reconcileActiveSession()
                when {
                    !hasActiveBinding -> _uiState.markSessionUnbound()
                    repository.isBusinessSessionReady() -> _uiState.markSessionReady(
                        unlocked = !requireLocalUnlock || !settingsStore.requiresUnlock(),
                    )
                    else -> _uiState.markSessionVerificationFailed(result?.exceptionOrNull())
                }
            } finally {
                sessionVerificationInFlight = false
            }
        }
    }

    fun abandonPendingEnrollment() {
        if (_uiState.value.binding || !repository.hasPendingBinding()) return
        viewModelScope.launch {
            _uiState.update { it.copy(binding = true, authMessage = null) }
            val error = try {
                repository.abandonPendingBinding()
                null
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (failure: Exception) {
                failure
            }
            val stillPending = repository.hasPendingBinding()
            _uiState.update {
                it.copy(
                    binding = false,
                    hasPendingEnrollment = stillPending,
                    authMessage = error?.toUiText(R.string.app_bind_failed),
                )
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

    fun setAuthMessage(message: UiText?) {
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

    fun selectThemeMode(mode: AppThemeMode) {
        settingsStore.saveAppThemeModeKey(mode.storageKey)
        _uiState.update {
            it.copy(themeMode = mode, authMessage = UiText.res(R.string.app_theme_mode_switched, mode.displayName))
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
        val currentMode = _uiState.value.themeMode
        val currentCurrency = _uiState.value.currency
        val currentBackground = _uiState.value.backgroundSettings
        viewModelScope.launch {
            repository.clearBinding()
            settingsStore.saveAppThemeModeKey(currentMode.storageKey)
            settingsStore.saveCurrencyCodeKey(currentCurrency.storageKey)
            _uiState.update {
                AppUiState(
                    themeMode = currentMode,
                    currency = currentCurrency,
                    currencyDisplay = CurrencyDisplay.Base,
                    backgroundSettings = currentBackground,
                )
            }
        }
    }
}

private fun MutableStateFlow<AppUiState>.markSessionUnbound() {
    update {
        it.copy(
            isBound = false,
            unlocked = false,
            sessionVerification = SessionVerificationState.Unbound,
            authMessage = null,
        )
    }
}

private fun MutableStateFlow<AppUiState>.markSessionReady(unlocked: Boolean) {
    update {
        it.copy(
            isBound = true,
            unlocked = unlocked,
            sessionVerification = SessionVerificationState.Ready,
            hasPendingEnrollment = false,
            authMessage = null,
        )
    }
}

private fun MutableStateFlow<AppUiState>.markSessionVerifying() {
    update {
        it.copy(
            isBound = true,
            unlocked = false,
            sessionVerification = SessionVerificationState.Verifying,
            authMessage = null,
        )
    }
}

private fun MutableStateFlow<AppUiState>.markSessionVerificationFailed(error: Throwable?) {
    update {
        it.copy(
            isBound = true,
            unlocked = false,
            sessionVerification = SessionVerificationState.Failed,
            authMessage = error?.toUiText(R.string.app_session_identity_pending)
                ?: UiText.res(R.string.app_session_identity_pending),
        )
    }
}

internal val BIND_RESTORE_FAILED_MESSAGE: UiText = UiText.res(R.string.app_bind_restore_failed)

private fun MutableStateFlow<AppUiState>.finishBinding(
    result: Result<BindServerResult>,
    hasPendingEnrollment: Boolean,
) {
    result.fold(
        onSuccess = { bindingResult ->
            update { state ->
                state.copy(
                    isBound = true,
                    unlocked = true,
                    binding = false,
                    sessionVerification = SessionVerificationState.Ready,
                    hasPendingEnrollment = false,
                    authMessage = if (bindingResult.confirmedRestoreFailed) {
                        BIND_RESTORE_FAILED_MESSAGE
                    } else {
                        null
                    },
                )
            }
        },
        onFailure = { error ->
            update {
                it.copy(
                    binding = false,
                    sessionVerification = SessionVerificationState.Unbound,
                    hasPendingEnrollment = hasPendingEnrollment,
                    authMessage = error.toUiText(R.string.app_bind_failed),
                )
            }
        },
    )
}
