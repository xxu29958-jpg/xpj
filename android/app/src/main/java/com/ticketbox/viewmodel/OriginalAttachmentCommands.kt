package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.OriginalAttachmentPayload
import com.ticketbox.data.repository.OriginalSubmission
import com.ticketbox.data.repository.originalPayloadAdapter
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import java.util.UUID
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

fun OriginalAttachmentViewModel.verifyReviewedImage() {
    val current = state.value
    if (!current.canVerify) return
    submitOriginalCommand(requireNotNull(command("verify_original")).copy(sha256 = current.reviewedDigest))
}

fun OriginalAttachmentViewModel.continueCleanup(cancel: Boolean) {
    val requestId = state.value.health?.cleanup?.requestId ?: return
    command(if (cancel) "cancel_original_cleanup" else "retry_original_cleanup")?.copy(cleanupRequestId = requestId)
        ?.let(::submitOriginalCommand)
}

/** Freeze target and OCC before opening the picker. Rotation/process restore keeps this original task. */
fun OriginalAttachmentViewModel.beginSelection(): Boolean {
    if (saved.get<String>("original_payload") != null) return false
    val payload = command("replenish_original")?.copy(sha256 = state.value.health?.expectedSha256) ?: return false
    if (payload.sha256 == null) return false
    saved["original_payload"] = originalPayloadAdapter.toJson(payload)
    saved["original_key"] = UUID.randomUUID().toString()
    mutableState.update { it.copy(localIntent = true, localIntentBound = true) }
    return true
}

fun OriginalAttachmentViewModel.selectedSource(uri: String?) {
    if (uri == null) {
        if (saved.get<String>("original_uri") == null) clearOriginalSelection()
        return
    }
    saved["original_uri"] = uri
    mutableState.update { it.copy(selectedSource = true) }
}

fun OriginalAttachmentViewModel.resumeSelectedSource(prepare: suspend (String) -> PreparedUploadImage?) {
    val uri = saved.get<String>("original_uri")
    val json = saved.get<String>("original_payload") ?: return
    val payload = runCatching { originalPayloadAdapter.fromJson(json) }.getOrNull() ?: return
    val key = saved.get<String>("original_key") ?: return
    if (payload.origin != originals.currentOriginalBinding() || state.value.busy) return
    if (payload.operation == "replenish_original" && uri == null) return
    deliver(OriginalSubmission(key, payload, uri?.let { source -> { prepare(source) } })) { clearOriginalSelection() }
}

fun OriginalAttachmentViewModel.clearOriginalSelection() {
    if (state.value.busy) return
    saved.remove<String>("original_uri")
    saved.remove<String>("original_payload")
    saved.remove<String>("original_key")
    mutableState.update { it.copy(selectedSource = false, localIntent = false, localIntentBound = false) }
}

fun OriginalAttachmentViewModel.recoverOriginal(rowId: Long, drop: Boolean) {
    val binding = state.value.access?.binding ?: return
    if (state.value.busy) return
    mutableState.update { it.copy(busy = true, message = null) }
    viewModelScope.launch {
        val result = originals.recoverOriginal(binding, rowId, drop)
        if (binding != originals.currentOriginalBinding()) return@launch
        mutableState.update { it.copy(busy = false, message = result.exceptionOrNull()?.toUiText(R.string.original_command_failed)) }
        refresh(preserveMessage = true)
    }
}

private fun OriginalAttachmentViewModel.command(operation: String): OriginalAttachmentPayload? {
    val current = state.value
    if (!current.canSubmit) return null
    val health = current.health ?: return null
    val binding = current.access?.binding ?: return null
    if (binding != originals.currentOriginalBinding()) return null
    return OriginalAttachmentPayload(operation = operation, expenseId = expenseId, publicId = health.publicId,
        expectedRowVersion = health.rowVersion, origin = binding)
}

private fun OriginalAttachmentViewModel.submitOriginalCommand(payload: OriginalAttachmentPayload) {
    val key = UUID.randomUUID().toString()
    saved["original_payload"] = originalPayloadAdapter.toJson(payload)
    saved["original_key"] = key
    mutableState.update { it.copy(localIntent = true, localIntentBound = true) }
    deliver(OriginalSubmission(key, payload)) { clearOriginalSelection() }
}

private fun OriginalAttachmentViewModel.deliver(request: OriginalSubmission, onAccepted: () -> Unit) {
    mutableState.update { it.copy(busy = true, message = null) }
    viewModelScope.launch {
        val result = originals.submitOriginal(request)
        if (request.payload.origin != originals.currentOriginalBinding()) return@launch
        mutableState.update { it.copy(busy = false, message = result.fold(
            onSuccess = { UiText.res(R.string.original_queued) }, onFailure = { it.toUiText(R.string.original_command_failed) })) }
        if (result.isSuccess) onAccepted()
    }
}
