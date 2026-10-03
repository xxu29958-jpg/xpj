package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
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
    val messageTone: MessageTone = MessageTone.Neutral,
    val listLoadState: LedgerListLoadState = LedgerListLoadState.Unknown,
    val rename: LedgerRenameDraft? = null,
)

data class LedgerRenameDraft(val ledger: LedgerSummary, val name: String = ledger.name, val fresh: Boolean = true)

enum class LedgerListLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

class LedgerSwitcherViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {
    private var binding = repository.currentBinding()
    private val _uiState = MutableStateFlow(cachedInitialState(repository.cachedLedgers()))
    val uiState: StateFlow<LedgerSwitcherUiState> = _uiState.asStateFlow()

    fun refresh() {
        if (_uiState.value.loading) return
        viewModelScope.launch {
            refreshLedgers(clearMessage = true)
        }
    }

    private suspend fun refreshLedgers(clearMessage: Boolean) {
        _uiState.update {
            if (clearMessage) {
                it.copy(
                    loading = true,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    listLoadState = LedgerListLoadState.Loading,
                )
            } else {
                it.copy(loading = true, listLoadState = LedgerListLoadState.Loading)
            }
        }
        repository.refreshLedgers(expectedBinding = binding)
            .onSuccess { ledgers ->
                _uiState.update {
                    it.copy(
                        loading = false,
                        ledgers = ledgers,
                        listLoadState = LedgerListLoadState.Loaded,
                        rename = it.rename?.let { draft ->
                            val current = ledgers.firstOrNull { row -> row.ledgerId == draft.ledger.ledgerId }
                            draft.copy(ledger = current ?: draft.ledger, fresh = current?.role == "owner")
                        },
                    )
                }
            }
            .onFailure { err ->
                _uiState.update {
                    it.copy(
                        loading = false,
                        message = err.toUiText(R.string.ledger_switcher_message_load_failed),
                        messageTone = MessageTone.Danger,
                        listLoadState = LedgerListLoadState.Failed,
                    )
                }
            }
    }

    /** Returns the new active ledger name on success so the caller can
     * trigger any session-level refresh (``onSwitched``). */
    fun switchTo(ledgerId: String, onSwitched: () -> Unit) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
            repository.switchLedger(ledgerId, expectedBinding = binding)
                .onSuccess { summary ->
                    binding = repository.currentBinding()
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = UiText.res(R.string.ledger_switcher_message_switched, summary.name),
                            messageTone = MessageTone.Success,
                        )
                    }
                    onSwitched()
                    refreshLedgers(clearMessage = false)
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = err.toUiText(R.string.ledger_switcher_message_switch_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun create(name: String, onCreated: () -> Unit) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
            repository.createLedger(name)
                .onSuccess { summary ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = UiText.res(R.string.ledger_switcher_message_created, summary.name),
                            messageTone = MessageTone.Success,
                        )
                    }
                    onCreated()
                    refreshLedgers(clearMessage = false)
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = err.toUiText(R.string.ledger_switcher_message_create_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun clearMessage() {
        _uiState.update { it.copy(message = null, messageTone = MessageTone.Neutral) }
    }

    /** Surface a non-network validation message (e.g. empty input). */
    fun showInputError(message: UiText) {
        _uiState.update { it.copy(message = message, messageTone = MessageTone.Danger) }
    }

    fun beginRename(ledger: LedgerSummary) {
        if (_uiState.value.loading || ledger.role != "owner") return
        _uiState.update { it.copy(rename = LedgerRenameDraft(ledger), message = null) }
    }

    fun changeRenameName(name: String) {
        if (!_uiState.value.loading) _uiState.update { it.copy(rename = it.rename?.copy(name = name.take(60))) }
    }

    fun dismissRename() {
        if (!_uiState.value.loading) _uiState.update { it.copy(rename = null) }
    }

    fun saveRename(onRenamed: () -> Unit) {
        val captured = binding ?: return
        val before = _uiState.value
        val draft = before.rename ?: return
        if (before.loading || !draft.fresh || draft.name.isBlank()) return
        _uiState.update { it.copy(loading = true, message = null) }
        viewModelScope.launch {
            repository.renameLedger(captured, draft.ledger, draft.name).onSuccess { saved ->
                _uiState.update { state -> state.copy(loading = false, rename = null,
                    ledgers = state.ledgers.map { if (it.ledgerId == saved.ledgerId) it.copy(name = saved.name) else it },
                    message = UiText.res(R.string.ledger_name_saved), messageTone = MessageTone.Success) }
                onRenamed()
            }.onFailure { failure ->
                if ((failure as? RepositoryException)?.httpStatusCode in setOf(403, 409)) {
                    _uiState.update { it.copy(rename = it.rename?.copy(fresh = false)) }
                    refreshLedgers(clearMessage = false)
                }
                _uiState.update { it.copy(loading = false, message = failure.toUiText(R.string.ledger_name_save_failed),
                    messageTone = MessageTone.Danger) }
            }
        }
    }
}

private fun cachedInitialState(ledgers: List<LedgerSummary>): LedgerSwitcherUiState =
    LedgerSwitcherUiState(
        ledgers = ledgers,
        listLoadState = if (ledgers.isEmpty()) {
            LedgerListLoadState.Unknown
        } else {
            LedgerListLoadState.Loaded
        },
    )
