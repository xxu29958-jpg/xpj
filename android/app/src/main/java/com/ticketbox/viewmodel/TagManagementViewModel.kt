package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.TagActions
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0043 slice C — tag management screen state. Online-only: every mutation
 * reloads the authoritative list from the server (no optimistic local edits) and
 * delete/merge expose a 5s 撤销 handle ([undoable]).
 */
data class TagManagementUiState(
    val tags: List<ManagedTag> = emptyList(),
    val loading: Boolean = false,
    val loadFailed: Boolean = false,
    val busy: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val undoable: TagUndoHandle? = null,
    val editor: TagEditorDraft? = null,
    val canModify: Boolean = false,
    val bindingChanged: Boolean = false,
    val showOriginalDraft: Boolean = false,
    // P4 stale-refresh: monotonically bumped after each successful tag mutation
    // (rename/delete/merge/undo). The screen observes it and tells the stats tab to
    // re-pull its tag list so a deleted/renamed tag stops lingering in the filter
    // chips (the stats VM persists across the settings round-trip and otherwise
    // only loads tags on init / ledger switch).
    val tagsChangedRevision: Int = 0,
)

/**
 * The handle a delete/merge leaves for undo: the mutation's public id + the
 * soft-deleted source tag's undo token (契约 2). [label] is the tag name for the
 * banner copy.
 */
data class TagUndoHandle(
    val mutationPublicId: String,
    val rowVersion: Long,
    val label: String,
)

class TagManagementViewModel(
    private val tagRepository: TagActions,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    private val drafts = TagManagementDraftStore(savedStateHandle)
    private val restored = drafts.read()
    private val binding = restored?.binding ?: tagRepository.captureBinding()
    private val _uiState = MutableStateFlow(TagManagementUiState(editor = restored?.editor))
    val uiState: StateFlow<TagManagementUiState> = _uiState.asStateFlow()

    init {
        binding?.let { drafts.write(it, restored?.editor) }
        viewModelScope.launch {
            tagRepository.observeLedgerAccess().collect { access ->
                val returnedToOriginal = _uiState.value.bindingChanged && access?.binding == binding
                val sameOwner = access?.binding?.let {
                    it.ownerKey == binding?.ownerKey && it.ledgerId == binding.ledgerId && it.serverUrl == binding.serverUrl
                } == true
                _uiState.update {
                    it.copy(
                        canModify = access?.binding == binding && access?.canModify == true,
                        bindingChanged = access?.binding != binding,
                        showOriginalDraft = sameOwner,
                        tags = if (sameOwner) it.tags else emptyList(),
                    )
                }
                if (returnedToOriginal) loadTags()
            }
        }
        loadTags()
    }

    fun editDraft(editor: TagEditorDraft?) {
        if (_uiState.value.busy) return
        binding?.let { drafts.write(it, editor) }
        _uiState.update { it.copy(editor = editor, message = null, messageTone = MessageTone.Neutral) }
    }

    fun loadTags() {
        if (_uiState.value.loading || _uiState.value.busy) return
        val originalBinding = binding ?: return
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    loadFailed = false,
                    message = null,
                    messageTone = MessageTone.Neutral,
                )
            }
            tagRepository.tags(originalBinding)
                .onSuccess { tags ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            loadFailed = false,
                            tags = tags.sortedByUsage(),
                            messageTone = MessageTone.Neutral,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            loadFailed = true,
                            message = error.toUiText(R.string.tag_management_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun renameTag(tag: ManagedTag, newName: String, requireOrphan: Boolean = false) {
        if (_uiState.value.busy) return
        if (newName.trim() == tag.name) return
        if (!canModifyOriginal()) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            tagRepository.renameTag(requireNotNull(binding), tag, newName, requireOrphan)
                .onSuccess { finishWithReload(message = UiText.res(R.string.tag_management_renamed, newName.trim())) }
                .onFailure { error -> handleRenameFailure(error, source = tag, attemptedName = newName) }
        }
    }

    /** 契约 5: on a key-collision (tag_conflict), if the colliding name maps to a
     *  LIVE tag in the current list, steer into a preselected merge dialog; else
     *  (e.g. the key is held by a soft-deleted tag, not in the list) fall back to
     *  the generic "请改用合并" message. Never auto-merges — the user confirms. */
    private fun handleRenameFailure(error: Throwable, source: ManagedTag, attemptedName: String) {
        val re = error as? RepositoryException
        if (re?.errorCode == "tag_conflict") {
            val wanted = attemptedName.trim()
            // Prefer the server's FRESH conflict token (ADR-0043 契约 5 details) over a
            // stale local-list entry so the prefilled merge doesn't immediately 409;
            // fall back to a local name match only if the backend sent no details.
            val conflictTagPublicId = re.conflictTagPublicId
            val conflictTagRowVersion = re.conflictTagRowVersion
            val target = if (conflictTagPublicId != null && conflictTagRowVersion != null) {
                _uiState.value.tags.firstOrNull { it.publicId == conflictTagPublicId }
                    ?.copy(rowVersion = conflictTagRowVersion)
            } else {
                _uiState.value.tags.firstOrNull {
                    it.publicId != source.publicId && it.name.trim().equals(wanted, ignoreCase = true)
                }
            }
            if (target != null) {
                val editor = TagEditorDraft(TagEditorAction.Merge, source,
                    requireOrphan = _uiState.value.editor?.requireOrphan ?: false, name = attemptedName, target = target)
                binding?.let { drafts.write(it, editor) }
                _uiState.update {
                    it.copy(
                        busy = false,
                        message = UiText.res(R.string.tag_management_rename_conflict_merge_prompt, target.name),
                        messageTone = MessageTone.Info,
                        editor = editor,
                    )
                }
                return
            }
            // Conflict is with a soft-deleted tag (key reserved, not in the live
            // list) → fall through to the generic "请改用合并" message.
        }
        failWith(error)
    }

    fun deleteTag(tag: ManagedTag, requireOrphan: Boolean = false) {
        if (_uiState.value.busy) return
        if (!canModifyOriginal()) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            tagRepository.deleteTag(requireNotNull(binding), tag, requireOrphan)
                .onSuccess { result ->
                    finishWithReload(
                        message = UiText.res(R.string.tag_management_deleted, tag.name),
                        undoable = TagUndoHandle(result.mutationPublicId, result.sourceTagRowVersion, tag.name),
                    )
                }
                .onFailure { error -> failWith(error) }
        }
    }

    fun mergeTags(source: ManagedTag, target: ManagedTag, requireOrphan: Boolean = false) {
        if (_uiState.value.busy) return
        if (source.publicId == target.publicId) return
        if (!canModifyOriginal()) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            tagRepository.mergeTags(requireNotNull(binding), source, target, requireOrphan)
                .onSuccess { result ->
                    finishWithReload(
                        message = UiText.res(R.string.tag_management_merged, source.name, target.name),
                        undoable = TagUndoHandle(result.mutationPublicId, result.sourceTagRowVersion, source.name),
                    )
                }
                .onFailure { error -> failWith(error) }
        }
    }

    fun undo() {
        // Busy gate: a stale undo banner left over from an earlier delete/merge must
        // not fire while a new rename/delete/merge is in flight (the button is also
        // disabled, this is the model-side backstop). Returns without consuming the
        // handle so the banner survives the in-flight op.
        if (_uiState.value.busy) return
        val handle = _uiState.value.undoable ?: return
        if (!canModifyOriginal()) return
        // Consume the affordance synchronously so a rapid second tap early-returns
        // above — the undo token is single-use; a double-fire would make the loser's
        // 404 overwrite the winner's success message.
        _uiState.update { it.copy(undoable = null, busy = true, message = null, messageTone = MessageTone.Neutral) }
        viewModelScope.launch {
            tagRepository.undoTagMutation(requireNotNull(binding), handle.mutationPublicId, handle.rowVersion)
                .onSuccess { result ->
                    val msg = if (result.skipped > 0) {
                        UiText.res(R.string.tag_management_undo_partial, result.applied, result.skipped)
                    } else {
                        UiText.res(R.string.tag_management_undo_done, handle.label)
                    }
                    val tone = if (result.skipped > 0) MessageTone.Info else MessageTone.Success
                    finishWithReload(message = msg, tone = tone)
                }
                .onFailure { error ->
                    // Window elapsed (tag_undo_not_found) or token stale → degrade.
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = tagErrorMessage(error),
                            messageTone = tagErrorTone(error),
                        )
                    }
                }
        }
    }

    /** Clear the undo affordance once its 5s window lapses (or after use). */
    fun dismissUndo() {
        _uiState.update { it.copy(undoable = null) }
    }

    private suspend fun finishWithReload(
        message: UiText,
        undoable: TagUndoHandle? = null,
        tone: MessageTone = MessageTone.Success,
    ) {
        binding?.let { drafts.write(it, null) }
        _uiState.update { it.copy(editor = null) }
        val refreshed = tagRepository.tags(requireNotNull(binding))
        _uiState.update {
            it.copy(
                // The accepted mutation invalidates the old list, including its
                // action tokens. Keep the result/undo, and retry only the read.
                tags = refreshed.getOrDefault(emptyList()).sortedByUsage(),
                loadFailed = refreshed.isFailure,
                busy = false,
                message = message,
                messageTone = tone,
                undoable = undoable,
                // Every path here is a committed tag mutation (rename/delete/merge/
                // undo success) → signal the stats tab to re-pull its tag list (P4).
                tagsChangedRevision = it.tagsChangedRevision + 1,
            )
        }
    }

    private fun failWith(error: Throwable) {
        _uiState.update {
            it.copy(busy = false, message = tagErrorMessage(error), messageTone = tagErrorTone(error))
        }
    }

    private fun canModifyOriginal(): Boolean =
        binding != null && tagRepository.captureBinding() == binding && tagRepository.canModifyLedger()
}

/** state_conflict has no entry in the shared error map (it's surface-agnostic);
 *  give it a tag-friendly line here without changing other surfaces' copy. Every
 *  other failure routes through [toUiText] (known code → R.string.error_*; else
 *  the resolved message; else the tag-action fallback). */
private fun tagErrorMessage(error: Throwable): UiText {
    val code = (error as? RepositoryException)?.errorCode
    if (code == "state_conflict") return UiText.res(R.string.tag_management_error_state_conflict)
    return error.toUiText(R.string.tag_management_action_failed)
}

private fun tagErrorTone(error: Throwable): MessageTone {
    val code = (error as? RepositoryException)?.errorCode
    return if (code == "tag_conflict") MessageTone.Info else MessageTone.Danger
}

private fun List<ManagedTag>.sortedByUsage(): List<ManagedTag> =
    sortedWith(compareByDescending<ManagedTag> { it.usageCount }.thenBy { it.name })
