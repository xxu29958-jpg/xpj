package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.TagActions
import com.ticketbox.domain.model.ManagedTag
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
    val busy: Boolean = false,
    val message: UiText? = null,
    val undoable: TagUndoHandle? = null,
    // 契约 5: a rename that collided with an existing live tag — the screen opens
    // the merge dialog preselected on [MergeSuggestion.target] (still user-
    // confirmed, NOT a silent merge). Null unless a conflict just resolved to a
    // live tag in the current list.
    val mergeSuggestion: MergeSuggestion? = null,
    // P4 stale-refresh: monotonically bumped after each successful tag mutation
    // (rename/delete/merge/undo). The screen observes it and tells the stats tab to
    // re-pull its tag list so a deleted/renamed tag stops lingering in the filter
    // chips (the stats VM persists across the settings round-trip and otherwise
    // only loads tags on init / ledger switch).
    val tagsChangedRevision: Int = 0,
)

/** A rename key-collision steered into a (user-confirmed) merge: rename [source]
 *  collided with the live [target]; offer to merge source → target instead. */
data class MergeSuggestion(
    val source: ManagedTag,
    val target: ManagedTag,
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
) : ViewModel() {
    private val _uiState = MutableStateFlow(TagManagementUiState())
    val uiState: StateFlow<TagManagementUiState> = _uiState.asStateFlow()

    init {
        loadTags()
    }

    fun loadTags() {
        viewModelScope.launch {
            tagRepository.tags()
                .onSuccess { tags -> _uiState.update { it.copy(tags = tags.sortedByUsage()) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.tag_management_load_failed)) } }
        }
    }

    fun renameTag(tag: ManagedTag, newName: String) {
        if (_uiState.value.busy) return
        if (newName.trim() == tag.name) return
        if (!tagRepository.canModifyLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            tagRepository.renameTag(tag.publicId, tag.rowVersion, newName)
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
                _uiState.update {
                    it.copy(
                        busy = false,
                        message = UiText.res(R.string.tag_management_rename_conflict_merge_prompt, target.name),
                        mergeSuggestion = MergeSuggestion(source, target),
                    )
                }
                return
            }
            // Conflict is with a soft-deleted tag (key reserved, not in the live
            // list) → fall through to the generic "请改用合并" message.
        }
        failWith(error)
    }

    /** The screen consumed the merge suggestion (opened the dialog). */
    fun consumeMergeSuggestion() {
        _uiState.update { it.copy(mergeSuggestion = null) }
    }

    fun deleteTag(tag: ManagedTag) {
        if (_uiState.value.busy) return
        if (!tagRepository.canModifyLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            tagRepository.deleteTag(tag.publicId, tag.rowVersion)
                .onSuccess { result ->
                    finishWithReload(
                        message = UiText.res(R.string.tag_management_deleted, tag.name),
                        undoable = TagUndoHandle(result.mutationPublicId, result.sourceTagRowVersion, tag.name),
                    )
                }
                .onFailure { error -> failWith(error) }
        }
    }

    fun mergeTags(source: ManagedTag, target: ManagedTag) {
        if (_uiState.value.busy) return
        if (source.publicId == target.publicId) return
        if (!tagRepository.canModifyLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            tagRepository.mergeTags(source.publicId, source.rowVersion, target.publicId, target.rowVersion)
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
        // Consume the affordance synchronously so a rapid second tap early-returns
        // above — the undo token is single-use; a double-fire would make the loser's
        // 404 overwrite the winner's success message.
        _uiState.update { it.copy(undoable = null, busy = true) }
        viewModelScope.launch {
            tagRepository.undoTagMutation(handle.mutationPublicId, handle.rowVersion)
                .onSuccess { result ->
                    val msg = if (result.skipped > 0) {
                        UiText.res(R.string.tag_management_undo_partial, result.applied, result.skipped)
                    } else {
                        UiText.res(R.string.tag_management_undo_done, handle.label)
                    }
                    finishWithReload(message = msg)
                }
                .onFailure { error ->
                    // Window elapsed (tag_undo_not_found) or token stale → degrade.
                    _uiState.update { it.copy(busy = false, message = tagErrorMessage(error)) }
                }
        }
    }

    /** Clear the undo affordance once its 5s window lapses (or after use). */
    fun dismissUndo() {
        _uiState.update { it.copy(undoable = null) }
    }

    private suspend fun finishWithReload(message: UiText, undoable: TagUndoHandle? = null) {
        val tags = tagRepository.tags().getOrNull()?.sortedByUsage() ?: _uiState.value.tags
        _uiState.update {
            it.copy(
                tags = tags,
                busy = false,
                message = message,
                undoable = undoable,
                // Every path here is a committed tag mutation (rename/delete/merge/
                // undo success) → signal the stats tab to re-pull its tag list (P4).
                tagsChangedRevision = it.tagsChangedRevision + 1,
            )
        }
    }

    private fun failWith(error: Throwable) {
        _uiState.update { it.copy(busy = false, message = tagErrorMessage(error)) }
    }
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

private fun List<ManagedTag>.sortedByUsage(): List<ManagedTag> =
    sortedWith(compareByDescending<ManagedTag> { it.usageCount }.thenBy { it.name })
