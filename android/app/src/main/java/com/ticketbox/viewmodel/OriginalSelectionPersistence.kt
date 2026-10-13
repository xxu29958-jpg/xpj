package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OriginalSubmission
import com.ticketbox.data.repository.originalPayloadAdapter
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal suspend fun OriginalAttachmentViewModel.restoreOriginalSelection(binding: LogicalSessionBinding) {
    val result = originals.originalSelections.loadOriginalSelection(binding, expenseId)
    if (binding != originals.currentOriginalBinding()) return
    result.onSuccess { draft ->
        if (draft != null) {
            saved["original_key"] = draft.key
            saved["original_payload"] = originalPayloadAdapter.toJson(draft.payload.copy(file = null))
            mutableState.update { it.copy(selectionDraft = draft, localIntent = true,
                localIntentBound = draft.payload.origin == binding, selectedSource = true) }
        }
        mutableState.update { it.copy(selectionLoaded = true) }
        if (draft?.payload?.origin == binding) readRetainedSelection()
    }.onFailure { error ->
        mutableState.update { it.copy(localIntent = true, message = error.toUiText(R.string.original_selection_load_failed)) }
    }
}

internal fun OriginalAttachmentViewModel.readRetainedSelection() {
    val draft = state.value.selectionDraft ?: return
    if (state.value.busy || !state.value.localIntentBound) return
    mutableState.update { it.copy(busy = true, message = null) }
    viewModelScope.launch {
        val result = originals.originalSelections.readOriginalSelection(draft)
        if (draft.payload.origin != originals.currentOriginalBinding() || state.value.selectionDraft !== draft) return@launch
        mutableState.update { it.copy(busy = false, selection = result.getOrNull()?.let(::OriginalImageSelection),
            selectionDisplayed = false, selectionConfirmed = false, message = result.exceptionOrNull()?.toUiText(R.string.original_source_unavailable)) }
    }
}

fun OriginalAttachmentViewModel.discardOriginalSelection() {
    val current = state.value
    val binding = current.access?.binding ?: return
    if (current.busy || !current.selectionLoaded) return
    val payload = saved.get<String>("original_payload")?.let(originalPayloadAdapter::fromJson) ?: return
    val key = saved.get<String>("original_key") ?: return
    mutableState.update { it.copy(busy = true, message = null) }
    viewModelScope.launch {
        val result = originals.originalSelections.discardOriginalSelection(binding, OriginalSubmission(key, payload))
        if (binding != originals.currentOriginalBinding()) return@launch
        mutableState.update { it.copy(busy = false, message = result.exceptionOrNull()?.toUiText(R.string.original_selection_save_failed)) }
        if (result.isSuccess) clearOriginalSelection()
    }
}

fun OriginalAttachmentViewModel.canLeaveOriginalSelection(): Boolean {
    val current = state.value
    val retained = current.selectionDraft != null || !current.localIntent || !current.localIntentBound
    if (!current.busy && retained) return true
    mutableState.update { it.copy(message = UiText.res(R.string.original_selection_leave_blocked)) }
    return false
}
