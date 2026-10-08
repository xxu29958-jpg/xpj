package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DeleteOutcome
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.MerchantAliasSaveOutcome
import com.ticketbox.data.repository.MerchantDraftKind
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MessageTone
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
    val aliasesLoadFailed: Boolean = false,
    val busy: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    // ADR-0038 undo: the just-(soft-)deleted alias, surfaced as a 5s 撤销
    // affordance. Null when there is nothing to undo.
    val undoableAlias: MerchantAlias? = null,
    // ADR-0054: a key-changing rename collided with an existing active merchant;
    // the screen opens a user-confirmed merge dialog with the target preselected.
    val mergeSuggestion: MerchantCatalogMergeSuggestion? = null,
    val changedRevision: Int = 0,
    val editorCompletion: MerchantEditorCompletion? = null,
    val drafts: MerchantDraftState = MerchantDraftState(),
)

enum class MerchantEditorKind { CreateCatalog, CreateAlias, RenameCatalog, MergeCatalog, VisibilityCatalog, DeleteCatalog, DeleteAlias }

/** Identifies only the editor whose command was accepted; other unsent forms stay intact. */
data class MerchantEditorCompletion(val kind: MerchantEditorKind, val publicId: String, val revision: Int)

data class MerchantCatalogMergeSuggestion(
    val source: MerchantCatalog,
    val target: MerchantCatalog,
)

@Suppress("TooManyFunctions")
class MerchantAliasViewModel(
    private val merchantRepository: MerchantRepository,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val originalBinding = merchantRepository.captureBinding()
    private val _uiState = MutableStateFlow(MerchantAliasUiState())
    val uiState: StateFlow<MerchantAliasUiState> = _uiState.asStateFlow()

    val drafts = MerchantDraftController(merchantRepository, viewModelScope,
        onFailure = { draft, error ->
            if (draft.kind == MerchantDraftKind.Rename) handleCatalogRenameFailure(error, requireNotNull(draft.source))
        },
        onCatalogRead = { catalog -> _uiState.update { it.copy(merchantCatalog = catalog.sortedMerchantCatalog()) } },
    ) { draft ->
        val kind = when (draft.kind) {
            MerchantDraftKind.Catalog -> MerchantEditorKind.CreateCatalog
            MerchantDraftKind.Alias -> MerchantEditorKind.CreateAlias
            MerchantDraftKind.Rename -> MerchantEditorKind.RenameCatalog
            MerchantDraftKind.Merge -> MerchantEditorKind.MergeCatalog
            MerchantDraftKind.Visibility -> MerchantEditorKind.VisibilityCatalog
            MerchantDraftKind.Delete -> MerchantEditorKind.DeleteCatalog
        }
        _uiState.update { state -> state.copy(changedRevision = state.changedRevision + 1,
            message = UiText.res(if (draft.kind.isCreation) R.string.merchant_creation_confirmed else R.string.merchant_command_confirmed),
            messageTone = MessageTone.Success,
            editorCompletion = MerchantEditorCompletion(kind, requireNotNull(draft.acceptedId), state.changedRevision + 1)) }
        loadMerchantCatalog(clearMessage = false, expectedBinding = draft.binding)
        loadMerchantAliases(clearMessage = false)
    }

    init {
        viewModelScope.launch { drafts.state.collect { drafts -> _uiState.update { it.copy(drafts = drafts) } } }
        loadMerchantCatalog(clearMessage = false)
        loadMerchantAliases(clearMessage = false)
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(repository.currentLedgerRole())
    }

    private fun loadMerchantCatalog(clearMessage: Boolean = true, expectedBinding: LogicalSessionBinding? = originalBinding) {
        viewModelScope.launch {
            if (clearMessage) {
                _uiState.update { it.copy(message = null, messageTone = MessageTone.Neutral) }
            }
            merchantRepository.merchantCatalog(includeHidden = true, expectedBinding = expectedBinding)
                .onSuccess { catalog -> _uiState.update { it.copy(merchantCatalog = catalog.sortedMerchantCatalog()) } }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.merchant_catalog_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun loadMerchantAliases(clearMessage: Boolean = true) {
        if (clearMessage && _uiState.value.busy) return
        if (clearMessage) _uiState.update { it.copy(busy = true) }
        viewModelScope.launch {
            if (clearMessage) {
                _uiState.update { it.copy(message = null, messageTone = MessageTone.Neutral) }
            }
            merchantRepository.merchantAliases()
                .onSuccess { aliases ->
                    _uiState.update {
                        it.copy(
                            merchantAliases = aliases.sortedMerchantAliases(),
                            aliasesLoadFailed = false,
                            busy = if (clearMessage) false else it.busy,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = if (!clearMessage && it.messageTone == MessageTone.Success) it.message
                                else error.toUiText(R.string.merchant_alias_load_failed),
                            messageTone = if (!clearMessage && it.messageTone == MessageTone.Success) it.messageTone else MessageTone.Danger,
                            merchantAliases = emptyList(),
                            aliasesLoadFailed = true,
                            busy = if (clearMessage) false else it.busy,
                        )
                    }
                }
        }
    }

    fun createMerchantCatalog(displayName: String) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger) }
            return
        }
        drafts.edit(MerchantDraftKind.Catalog, displayName)
        drafts.submit(MerchantDraftKind.Catalog)
    }

    private fun handleCatalogRenameFailure(error: Throwable, source: MerchantCatalog) {
        val exception = error as? RepositoryException
        val target = exception?.toMergeTarget(_uiState.value.merchantCatalog)
        if (target != null) {
            _uiState.update {
                it.copy(
                    busy = false,
                    message = UiText.res(R.string.merchant_catalog_rename_conflict_merge_prompt, target.displayName),
                    messageTone = MessageTone.Info,
                    mergeSuggestion = MerchantCatalogMergeSuggestion(source, target),
                )
            }
            return
        }
        _uiState.update { it.copy(busy = false, message = catalogErrorMessage(error), messageTone = MessageTone.Danger) }
    }

    /** The screen consumed the merge suggestion and opened the dialog. */
    fun consumeMergeSuggestion() {
        _uiState.update { it.copy(mergeSuggestion = null) }
    }

    fun dismissMessage() {
        _uiState.update { it.copy(message = null, messageTone = MessageTone.Neutral) }
    }

    fun createMerchantAlias(canonicalMerchant: String, alias: String) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger) }
            return
        }
        drafts.edit(MerchantDraftKind.Alias, "", canonicalMerchant, alias)
        drafts.submit(MerchantDraftKind.Alias)
    }

    fun toggleMerchantAlias(alias: MerchantAlias) {
        if (_uiState.value.busy) return
        if (!canModifyCurrentLedger()) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            // ADR-0038 PR-2g.6: offline-aware toggle. IOException →
            // enqueue + MerchantAliasSaveOutcome.Queued (optimistic
            // flipped enabled); chained POST not used by this VM so
            // it's safe to route through outbox.
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
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
                    val tone = when (outcome) {
                        is MerchantAliasSaveOutcome.Synced -> MessageTone.Success
                        is MerchantAliasSaveOutcome.Queued -> MessageTone.Info
                    }
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases
                                .map { if (it.publicId == outcome.alias.publicId) outcome.alias else it }
                                .sortedMerchantAliases(),
                            busy = false,
                            message = message,
                            messageTone = tone,
                            changedRevision = state.changedRevision + 1,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.merchant_alias_update_failed),
                            busy = false,
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun deleteMerchantAlias(alias: MerchantAlias) {
        if (_uiState.value.busy) return
        if (!canModifyCurrentLedger()) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            // ADR-0038 PR-2g.5: offline-aware DELETE. IOException →
            // enqueue + DeleteOutcome.Queued; row removed from UI
            // either way (synced vs queued only changes the message).
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            merchantRepository.deleteMerchantAliasAllowingOffline(alias)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        DeleteOutcome.Synced -> UiText.res(R.string.merchant_alias_deleted)
                        DeleteOutcome.Queued -> UiText.res(R.string.merchant_alias_deleted_offline)
                    }
                    val tone = when (outcome) {
                        DeleteOutcome.Synced -> MessageTone.Success
                        DeleteOutcome.Queued -> MessageTone.Info
                    }
                    // ADR-0038 undo: offer 撤销 only when the server already
                    // holds the soft-deleted row (Synced). A queued offline
                    // delete has nothing to restore via the API yet.
                    val undoable = if (outcome == DeleteOutcome.Synced) alias else null
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases.filterNot { it.publicId == alias.publicId },
                            busy = false,
                            message = message,
                            messageTone = tone,
                            undoableAlias = undoable,
                            changedRevision = state.changedRevision + 1,
                            editorCompletion = MerchantEditorCompletion(
                                MerchantEditorKind.DeleteAlias, alias.publicId, state.changedRevision + 1,
                            ),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.merchant_alias_delete_failed),
                            busy = false,
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun undoDelete() {
        if (_uiState.value.busy) return
        val target = _uiState.value.undoableAlias ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            merchantRepository.undoMerchantAlias(target.publicId)
                .onSuccess { restored ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = (state.merchantAliases + restored).sortedMerchantAliases(),
                            busy = false,
                            message = UiText.res(R.string.merchant_alias_restored),
                            messageTone = MessageTone.Success,
                            undoableAlias = null,
                            changedRevision = state.changedRevision + 1,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.merchant_alias_restore_failed),
                            busy = false,
                            messageTone = MessageTone.Danger,
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
