package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Settings → Ledger switcher.
 *
 * Pulled out of ``LedgerSwitcherScreen`` to comply with the Android layer
 * rule (Screen → ViewModel → Repository → IO). The screen previously
 * received ``LedgerRepository`` directly and embedded repository calls in
 * Composable bodies, which made testing and configuration-change behavior
 * fragile.
 */
data class LedgerSwitcherUiState(
    val ledgers: List<LedgerSummary> = emptyList(),
    val loading: Boolean = false,
    val message: UiText? = null,
)

class LedgerSwitcherViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        LedgerSwitcherUiState(ledgers = repository.cachedLedgers()),
    )
    val uiState: StateFlow<LedgerSwitcherUiState> = _uiState.asStateFlow()

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.refreshLedgers()
                .onSuccess { ledgers ->
                    _uiState.update { it.copy(loading = false, ledgers = ledgers) }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = err.toUiText(R.string.ledger_switcher_message_load_failed),
                        )
                    }
                }
        }
    }

    /** Returns the new active ledger name on success so the caller can
     * trigger any session-level refresh (``onSwitched``). */
    fun switchTo(ledgerId: String, onSwitched: () -> Unit) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.switchLedger(ledgerId)
                .onSuccess { summary ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = UiText.res(R.string.ledger_switcher_message_switched, summary.name),
                        )
                    }
                    onSwitched()
                    refresh()
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = err.toUiText(R.string.ledger_switcher_message_switch_failed),
                        )
                    }
                }
        }
    }

    fun create(name: String, onCreated: () -> Unit) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.createLedger(name)
                .onSuccess { summary ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = UiText.res(R.string.ledger_switcher_message_created, summary.name),
                        )
                    }
                    onCreated()
                    refresh()
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = err.toUiText(R.string.ledger_switcher_message_create_failed),
                        )
                    }
                }
        }
    }

    fun clearMessage() {
        _uiState.update { it.copy(message = null) }
    }

    /** Surface a non-network validation message (e.g. empty input). */
    fun showInputError(message: UiText) {
        _uiState.update { it.copy(message = message) }
    }
}
