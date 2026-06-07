package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DeleteOutcome
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.MerchantAliasSaveOutcome
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class MerchantAliasUiState(
    val merchantAliases: List<MerchantAlias> = emptyList(),
    val busy: Boolean = false,
    val message: UiText? = null,
    // ADR-0038 undo: the just-(soft-)deleted alias, surfaced as a 5s 撤销
    // affordance. Null when there is nothing to undo.
    val undoableAlias: MerchantAlias? = null,
)

class MerchantAliasViewModel(
    private val merchantRepository: MerchantRepository,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MerchantAliasUiState())
    val uiState: StateFlow<MerchantAliasUiState> = _uiState.asStateFlow()

    init {
        loadMerchantAliases()
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(repository.currentLedgerRole())
    }

    fun loadMerchantAliases() {
        viewModelScope.launch {
            merchantRepository.merchantAliases()
                .onSuccess { aliases -> _uiState.update { it.copy(merchantAliases = aliases.sortedMerchantAliases()) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.merchant_alias_load_failed)) } }
        }
    }

    fun createMerchantAlias(canonicalMerchant: String, alias: String) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            merchantRepository.createMerchantAlias(canonicalMerchant = canonicalMerchant, alias = alias)
                .onSuccess { created ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = (state.merchantAliases + created).sortedMerchantAliases(),
                            busy = false,
                            message = UiText.res(R.string.merchant_alias_added),
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.merchant_alias_add_failed)) } }
        }
    }

    fun toggleMerchantAlias(alias: MerchantAlias) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            // ADR-0038 PR-2g.6: offline-aware toggle. IOException →
            // enqueue + MerchantAliasSaveOutcome.Queued (optimistic
            // flipped enabled); chained POST not used by this VM so
            // it's safe to route through outbox.
            merchantRepository.updateMerchantAliasAllowingOffline(
                baseline = alias,
                enabled = !alias.enabled,
            )
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is MerchantAliasSaveOutcome.Synced ->
                            if (outcome.alias.enabled) {
                                UiText.res(R.string.merchant_alias_enabled)
                            } else {
                                UiText.res(R.string.merchant_alias_disabled)
                            }
                        is MerchantAliasSaveOutcome.Queued ->
                            if (outcome.alias.enabled) {
                                UiText.res(R.string.merchant_alias_enabled_offline)
                            } else {
                                UiText.res(R.string.merchant_alias_disabled_offline)
                            }
                    }
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases
                                .map { if (it.publicId == outcome.alias.publicId) outcome.alias else it }
                                .sortedMerchantAliases(),
                            message = message,
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.merchant_alias_update_failed)) } }
        }
    }

    fun deleteMerchantAlias(alias: MerchantAlias) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            // ADR-0038 PR-2g.5: offline-aware DELETE. IOException →
            // enqueue + DeleteOutcome.Queued; row removed from UI
            // either way (synced vs queued only changes the message).
            merchantRepository.deleteMerchantAliasAllowingOffline(alias)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        DeleteOutcome.Synced -> UiText.res(R.string.merchant_alias_deleted)
                        DeleteOutcome.Queued -> UiText.res(R.string.merchant_alias_deleted_offline)
                    }
                    // ADR-0038 undo: offer 撤销 only when the server already
                    // holds the soft-deleted row (Synced). A queued offline
                    // delete has nothing to restore via the API yet.
                    val undoable = if (outcome == DeleteOutcome.Synced) alias else null
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases.filterNot { it.publicId == alias.publicId },
                            message = message,
                            undoableAlias = undoable,
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.merchant_alias_delete_failed)) } }
        }
    }

    fun undoDelete() {
        val target = _uiState.value.undoableAlias ?: return
        viewModelScope.launch {
            merchantRepository.undoMerchantAlias(target.publicId)
                .onSuccess { restored ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = (state.merchantAliases + restored).sortedMerchantAliases(),
                            message = UiText.res(R.string.merchant_alias_restored),
                            undoableAlias = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.merchant_alias_restore_failed),
                            undoableAlias = null,
                        )
                    }
                }
        }
    }

    /** Clear the undo affordance once its 5s window lapses (or after use). */
    fun dismissUndo() {
        _uiState.update { it.copy(undoableAlias = null) }
    }
}

private fun List<MerchantAlias>.sortedMerchantAliases(): List<MerchantAlias> =
    sortedWith(
        compareByDescending<MerchantAlias> { it.enabled }
            .thenBy { it.canonicalKey }
            .thenBy { it.aliasKey },
    )
