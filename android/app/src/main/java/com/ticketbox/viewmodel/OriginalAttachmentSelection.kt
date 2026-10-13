package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.OriginalSubmission
import com.ticketbox.data.repository.originalPayloadAdapter
import com.ticketbox.upload.PreparedUploadImage
import java.util.UUID
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Freeze target and OCC before opening the picker. Rotation/process restore keeps this original task. */
fun OriginalAttachmentViewModel.beginSelection(): Boolean {
    if (saved.get<String>("original_payload") != null) return false
    val health = state.value.health ?: return false
    val operation = state.value.selectionOperation ?: return false
    val payload = command(operation)?.copy(sha256 = health.expectedSha256) ?: return false
    saved["original_payload"] = originalPayloadAdapter.toJson(payload)
    saved["original_key"] = UUID.randomUUID().toString()
    mutableState.update { it.copy(localIntent = true, localIntentBound = true) }
    return true
}

fun OriginalAttachmentViewModel.selectedSource(uri: String?) {
    if (state.value.busy || saved.get<String>("original_payload") == null) return
    if (uri == null) {
        if (saved.get<String>("original_uri") == null) clearOriginalSelection()
        return
    }
    saved["original_uri"] = uri
    mutableState.update { it.copy(selectedSource = true, selection = null, selectionDisplayed = false, selectionConfirmed = false) }
}

fun OriginalAttachmentViewModel.resumeSelectedSource(prepare: suspend (String) -> PreparedUploadImage?) {
    if (!state.value.canResumeSelection) return
    if (!state.value.selectionLoaded) {
        state.value.access?.binding?.let { binding -> viewModelScope.launch { restoreOriginalSelection(binding) } }
        return
    }
    if (state.value.selectionDraft != null) { readRetainedSelection(); return }
    val uri = saved.get<String>("original_uri")
    val json = saved.get<String>("original_payload") ?: return
    val payload = runCatching { originalPayloadAdapter.fromJson(json) }.getOrNull() ?: return
    val key = saved.get<String>("original_key") ?: return
    if (payload.origin != originals.currentOriginalBinding() || state.value.busy) return
    if (reconcileSubmittedSelection()) return
    if (payload.operation !in setOf("attach_original", "replenish_original")) {
        deliver(OriginalSubmission(key, payload)) { clearOriginalSelection() }
        return
    }
    if (uri == null) return
    val displayed = state.value.selection?.source
    loadSelectedImage(uri, payload.origin) { displayed ?: prepare(it) }
}

/** Admit the exact bytes displayed and confirmed, never reopen a mutable provider URI here. */
fun OriginalAttachmentViewModel.submitSelectedSource() {
    if (!state.value.canConfirmSelection) return
    val selection = state.value.selection ?: return
    val draft = state.value.selectionDraft ?: return
    if (draft.payload.origin != originals.currentOriginalBinding()) return
    deliver(OriginalSubmission(draft.key, draft.payload, draft) { selection.source }) { clearOriginalSelection() }
}

/** A visible Room command is authoritative even if its local admission reply was lost. */
internal fun OriginalAttachmentViewModel.reconcileSubmittedSelection(): Boolean {
    if (state.value.busy || !state.value.localIntentBound) return false
    val key = saved.get<String>("original_key") ?: return false
    val json = saved.get<String>("original_payload") ?: return false
    val payload = runCatching { originalPayloadAdapter.fromJson(json) }.getOrNull() ?: return false
    if (state.value.commands.none { it.row.idempotencyKey == key && it.payload?.copy(file = null) == payload }) return false
    clearOriginalSelection()
    return true
}

fun OriginalAttachmentViewModel.clearOriginalSelection() {
    if (state.value.busy) return
    saved.remove<String>("original_uri")
    saved.remove<String>("original_payload")
    saved.remove<String>("original_key")
    mutableState.update { it.copy(selectedSource = false, selection = null, selectionDraft = null, selectionDisplayed = false,
        selectionConfirmed = false, localIntent = false, localIntentBound = false) }
}
