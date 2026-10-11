package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.OriginalAttachmentPayload
import com.ticketbox.data.repository.OriginalSubmission
import com.ticketbox.data.repository.originalPayloadAdapter
import com.ticketbox.domain.model.UiText
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

internal fun OriginalAttachmentViewModel.command(operation: String): OriginalAttachmentPayload? {
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

internal fun OriginalAttachmentViewModel.deliver(request: OriginalSubmission, onAccepted: () -> Unit) {
    mutableState.update { it.copy(busy = true, message = null) }
    viewModelScope.launch {
        val result = originals.submitOriginal(request)
        if (request.payload.origin != originals.currentOriginalBinding()) return@launch
        mutableState.update { it.copy(busy = false, message = result.fold(
            onSuccess = { UiText.res(R.string.original_queued) }, onFailure = { it.toUiText(R.string.original_command_failed) })) }
        if (result.isSuccess) onAccepted()
        else if (reconcileSubmittedSelection()) mutableState.update { it.copy(message = UiText.res(R.string.original_queued)) }
    }
}
