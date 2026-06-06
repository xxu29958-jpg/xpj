package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.TagActions
import com.ticketbox.domain.model.ManagedTag
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
    val message: String? = null,
    val undoable: TagUndoHandle? = null,
    // 契约 5: a rename that collided with an existing live tag — the screen opens
    // the merge dialog preselected on [MergeSuggestion.target] (still user-
    // confirmed, NOT a silent merge). Null unless a conflict just resolved to a
    // live tag in the current list.
    val mergeSuggestion: MergeSuggestion? = null,
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
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "标签暂时打不开。") } }
        }
    }

    fun renameTag(tag: ManagedTag, newName: String) {
        if (newName.trim() == tag.name) return
        if (!tagRepository.canModifyLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            tagRepository.renameTag(tag.publicId, tag.rowVersion, newName)
                .onSuccess { finishWithReload(message = "标签已重命名为「${newName.trim()}」") }
                .onFailure { error -> handleRenameFailure(error, source = tag, attemptedName = newName) }
        }
    }

    /** 契约 5: on a key-collision (tag_conflict), if the colliding name maps to a
     *  LIVE tag in the current list, steer into a preselected merge dialog; else
     *  (e.g. the key is held by a soft-deleted tag, not in the list) fall back to
     *  the generic "请改用合并" message. Never auto-merges — the user confirms. */
    private fun handleRenameFailure(error: Throwable, source: ManagedTag, attemptedName: String) {
        if ((error as? RepositoryException)?.errorCode == "tag_conflict") {
            val wanted = attemptedName.trim()
            val target = _uiState.value.tags.firstOrNull {
                it.publicId != source.publicId && it.name.trim().equals(wanted, ignoreCase = true)
            }
            if (target != null) {
                _uiState.update {
                    it.copy(
                        busy = false,
                        message = "「$wanted」已存在，合并到它？",
                        mergeSuggestion = MergeSuggestion(source, target),
                    )
                }
                return
            }
        }
        failWith(error)
    }

    /** The screen consumed the merge suggestion (opened the dialog). */
    fun consumeMergeSuggestion() {
        _uiState.update { it.copy(mergeSuggestion = null) }
    }

    fun deleteTag(tag: ManagedTag) {
        if (!tagRepository.canModifyLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            tagRepository.deleteTag(tag.publicId, tag.rowVersion)
                .onSuccess { result ->
                    finishWithReload(
                        message = "已删除标签「${tag.name}」",
                        undoable = TagUndoHandle(result.mutationPublicId, result.sourceTagRowVersion, tag.name),
                    )
                }
                .onFailure { error -> failWith(error) }
        }
    }

    fun mergeTags(source: ManagedTag, target: ManagedTag) {
        if (source.publicId == target.publicId) return
        if (!tagRepository.canModifyLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            tagRepository.mergeTags(source.publicId, source.rowVersion, target.publicId, target.rowVersion)
                .onSuccess { result ->
                    finishWithReload(
                        message = "已把「${source.name}」合并到「${target.name}」",
                        undoable = TagUndoHandle(result.mutationPublicId, result.sourceTagRowVersion, source.name),
                    )
                }
                .onFailure { error -> failWith(error) }
        }
    }

    fun undo() {
        val handle = _uiState.value.undoable ?: return
        // Consume the affordance synchronously so a rapid second tap early-returns
        // above — the undo token is single-use; a double-fire would make the loser's
        // 404 overwrite the winner's success message.
        _uiState.update { it.copy(undoable = null, busy = true) }
        viewModelScope.launch {
            tagRepository.undoTagMutation(handle.mutationPublicId, handle.rowVersion)
                .onSuccess { result ->
                    val msg = if (result.skipped > 0) {
                        "已撤销（恢复 ${result.applied} 笔，${result.skipped} 笔已改动跳过）"
                    } else {
                        "已撤销「${handle.label}」"
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

    private suspend fun finishWithReload(message: String, undoable: TagUndoHandle? = null) {
        val tags = tagRepository.tags().getOrNull()?.sortedByUsage() ?: _uiState.value.tags
        _uiState.update { it.copy(tags = tags, busy = false, message = message, undoable = undoable) }
    }

    private fun failWith(error: Throwable) {
        _uiState.update { it.copy(busy = false, message = tagErrorMessage(error)) }
    }
}

/** state_conflict has no entry in the shared error map (it's surface-agnostic);
 *  give it a tag-friendly line here without changing other surfaces' copy. */
private fun tagErrorMessage(error: Throwable): String {
    val code = (error as? RepositoryException)?.errorCode
    if (code == "state_conflict") return "标签已在其它端被修改，请刷新后重试。"
    return error.message ?: "操作没有成功，请稍后再试。"
}

private fun List<ManagedTag>.sortedByUsage(): List<ManagedTag> =
    sortedWith(compareByDescending<ManagedTag> { it.usageCount }.thenBy { it.name })
