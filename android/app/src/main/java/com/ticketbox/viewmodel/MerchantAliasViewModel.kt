package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DeleteOutcome
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.MerchantAliasSaveOutcome
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.MerchantCatalogMergeResult
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class MerchantAliasUiState(
    val merchantCatalog: List<MerchantCatalog> = emptyList(),
    val merchantAliases: List<MerchantAlias> = emptyList(),
    val busy: Boolean = false,
    val message: UiText? = null,
    // ADR-0038 undo: the just-(soft-)deleted alias, surfaced as a 5s 撤销
    // affordance. Null when there is nothing to undo.
    val undoableAlias: MerchantAlias? = null,
    // ADR-0054: a key-changing rename collided with an existing active merchant;
    // the screen opens a user-confirmed merge dialog with the target preselected.
    val mergeSuggestion: MerchantCatalogMergeSuggestion? = null,
)

data class MerchantCatalogMergeSuggestion(
    val source: MerchantCatalog,
    val target: MerchantCatalog,
)

@Suppress("TooManyFunctions")
class MerchantAliasViewModel(
    private val merchantRepository: MerchantRepository,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MerchantAliasUiState())
    val uiState: StateFlow<MerchantAliasUiState> = _uiState.asStateFlow()

    init {
        loadMerchantCatalog()
        loadMerchantAliases()
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(repository.currentLedgerRole())
    }

    private fun loadMerchantCatalog() {
        viewModelScope.launch {
            merchantRepository.merchantCatalog(includeHidden = true)
                .onSuccess { catalog -> _uiState.update { it.copy(merchantCatalog = catalog.sortedMerchantCatalog()) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.merchant_catalog_load_failed)) } }
        }
    }

    fun loadMerchantAliases() {
        viewModelScope.launch {
            merchantRepository.merchantAliases()
                .onSuccess { aliases -> _uiState.update { it.copy(merchantAliases = aliases.sortedMerchantAliases()) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.merchant_alias_load_failed)) } }
        }
    }

    fun createMerchantCatalog(displayName: String) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            merchantRepository.createMerchantCatalog(displayName = displayName)
                .onSuccess { created ->
                    _uiState.update { state ->
                        state.copy(
                            merchantCatalog = (state.merchantCatalog + created).sortedMerchantCatalog(),
                            busy = false,
                            message = UiText.res(R.string.merchant_catalog_added),
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.merchant_catalog_add_failed)) } }
        }
    }

    fun toggleMerchantCatalog(item: MerchantCatalog) {
        if (_uiState.value.busy || item.isMerged) return
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            val nextStatus = if (item.isActive) "hidden" else "active"
            merchantRepository.updateMerchantCatalog(
                publicId = item.publicId,
                expectedRowVersion = item.rowVersion,
                status = nextStatus,
            )
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            merchantCatalog = state.merchantCatalog
                                .map { if (it.publicId == updated.publicId) updated else it }
                                .sortedMerchantCatalog(),
                            message = if (updated.isActive) {
                                UiText.res(R.string.merchant_catalog_visible)
                            } else {
                                UiText.res(R.string.merchant_catalog_hidden)
                            },
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = catalogErrorMessage(error)) } }
        }
    }

    fun renameMerchantCatalog(item: MerchantCatalog, displayName: String) {
        if (_uiState.value.busy || item.isMerged) return
        val cleanName = displayName.trim()
        if (cleanName == item.displayName) return
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, mergeSuggestion = null) }
            merchantRepository.updateMerchantCatalog(
                publicId = item.publicId,
                expectedRowVersion = item.rowVersion,
                displayName = cleanName,
            )
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            merchantCatalog = state.merchantCatalog
                                .map { if (it.publicId == updated.publicId) updated else it }
                                .sortedMerchantCatalog(),
                            busy = false,
                            message = UiText.res(R.string.merchant_catalog_renamed, updated.displayName),
                        )
                    }
                }
                .onFailure { error -> handleCatalogRenameFailure(error, source = item) }
        }
    }

    private fun handleCatalogRenameFailure(error: Throwable, source: MerchantCatalog) {
        val exception = error as? RepositoryException
        val target = exception?.toMergeTarget(_uiState.value.merchantCatalog)
        if (target != null) {
            _uiState.update {
                it.copy(
                    busy = false,
                    message = UiText.res(R.string.merchant_catalog_rename_conflict_merge_prompt, target.displayName),
                    mergeSuggestion = MerchantCatalogMergeSuggestion(source, target),
                )
            }
            return
        }
        _uiState.update { it.copy(busy = false, message = catalogErrorMessage(error)) }
    }

    /** The screen consumed the merge suggestion and opened the dialog. */
    fun consumeMergeSuggestion() {
        _uiState.update { it.copy(mergeSuggestion = null) }
    }

    fun mergeMerchantCatalog(
        source: MerchantCatalog,
        target: MerchantCatalog,
        aliasPolicy: MerchantCatalogAliasPolicy,
    ) {
        if (_uiState.value.busy || source.publicId == target.publicId || source.isMerged || !target.isActive) return
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, mergeSuggestion = null) }
            merchantRepository.mergeMerchantCatalog(
                sourcePublicId = source.publicId,
                sourceRowVersion = source.rowVersion,
                targetPublicId = target.publicId,
                targetRowVersion = target.rowVersion,
                aliasPolicy = aliasPolicy,
            )
                .onSuccess { result -> finishCatalogMerge(source, target, result, aliasPolicy) }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = catalogErrorMessage(error)) } }
        }
    }

    private suspend fun finishCatalogMerge(
        source: MerchantCatalog,
        target: MerchantCatalog,
        result: MerchantCatalogMergeResult,
        aliasPolicy: MerchantCatalogAliasPolicy,
    ) {
        val refreshedAliases = if (result.createdAliasPublicId != null) {
            merchantRepository.merchantAliases().getOrNull()?.sortedMerchantAliases()
        } else {
            null
        }
        _uiState.update { state ->
            state.copy(
                merchantCatalog = state.merchantCatalog
                    .map { item ->
                        when (item.publicId) {
                            result.source.publicId -> result.source
                            result.target.publicId -> result.target
                            else -> item
                        }
                    }
                    .sortedMerchantCatalog(),
                merchantAliases = refreshedAliases ?: state.merchantAliases,
                busy = false,
                message = if (aliasPolicy == MerchantCatalogAliasPolicy.CreateSourceAlias) {
                    UiText.res(R.string.merchant_catalog_merged_with_alias, source.displayName, target.displayName)
                } else {
                    UiText.res(R.string.merchant_catalog_merged, source.displayName, target.displayName)
                },
            )
        }
    }

    fun deleteMerchantCatalog(item: MerchantCatalog) {
        if (_uiState.value.busy || item.isMerged) return
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            merchantRepository.deleteMerchantCatalog(
                publicId = item.publicId,
                expectedRowVersion = item.rowVersion,
            )
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(
                            merchantCatalog = state.merchantCatalog.filterNot { it.publicId == item.publicId },
                            message = UiText.res(R.string.merchant_catalog_deleted),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(message = catalogErrorMessage(error, R.string.merchant_catalog_delete_failed)) }
                }
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

private fun List<MerchantCatalog>.sortedMerchantCatalog(): List<MerchantCatalog> =
    sortedWith(
        compareBy<MerchantCatalog> { it.catalogStatusRank() }
            .thenBy { it.merchantKey }
            .thenBy { it.displayName },
    )

private fun MerchantCatalog.catalogStatusRank(): Int =
    when (status) {
        "active" -> 0
        "hidden" -> 1
        "merged" -> 2
        else -> 3
    }

private fun RepositoryException.toMergeTarget(catalog: List<MerchantCatalog>): MerchantCatalog? {
    if (errorCode != "state_conflict") return null
    val publicId = conflictMerchantPublicId ?: return null
    val rowVersion = conflictMerchantRowVersion ?: return null
    if (conflictMerchantDeleted == true) return null
    val local = catalog.firstOrNull { it.publicId == publicId } ?: return null
    val target = local.copy(
        displayName = conflictMerchantDisplayName?.trim()?.takeIf { it.isNotBlank() } ?: local.displayName,
        status = conflictMerchantStatus?.trim()?.takeIf { it.isNotBlank() } ?: local.status,
        rowVersion = rowVersion,
    )
    return target.takeIf { it.isActive }
}

private fun catalogErrorMessage(
    error: Throwable,
    fallback: Int = R.string.merchant_catalog_update_failed,
): UiText {
    val exception = error as? RepositoryException
    if (exception?.errorCode == "state_conflict") {
        if (exception.conflictAliasPublicId != null) {
            return UiText.res(R.string.merchant_catalog_error_alias_conflict)
        }
        return UiText.res(R.string.merchant_catalog_error_state_conflict)
    }
    return error.toUiText(fallback)
}
