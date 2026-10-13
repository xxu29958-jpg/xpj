package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingUploadIntent
import com.ticketbox.data.repository.NON_RETRYABLE_UPLOAD_ERRORS
import com.ticketbox.data.repository.UPLOAD_CAPACITY_FULL
import com.ticketbox.data.repository.UploadIntentObservation
import com.ticketbox.data.repository.isUploadIntentFileKey
import com.ticketbox.domain.model.UiText

/** Read-only projection of the oldest unfinished, or most recent completed, Room group. */
data class PendingUploadUiState(
    val groupId: String? = null,
    val inFlight: Boolean = false,
    val failedCount: Int = 0,
    val retryable: Boolean = false,
    val message: UiText? = null,
    val originals: List<PendingUploadOriginalUi> = emptyList(),
)

data class PendingUploadOriginalUi(
    val position: Int,
    val fileName: String?,
    val status: PendingMutationStatus = PendingMutationStatus.Pending,
    val expenseId: Long? = null,
)

internal fun UploadIntentObservation.toPendingUploadUiState(): PendingUploadUiState {
    val unfinished = uploads.filter { it.row.status != PendingMutationStatus.Done }
    val first = unfinished.firstOrNull() ?: uploads.lastOrNull() ?: return PendingUploadUiState()
    val group = uploads.filter { it.row.targetId == first.row.targetId }
    val groupId = first.row.targetId.removePrefix("upload_batch:")
        .takeIf { first.row.targetId == "upload_batch:$it" && isUploadIntentFileKey(it) }
    val pending = group.filter { it.row.status != PendingMutationStatus.Done }
    val failures = pending.filter { it.row.status in UPLOAD_FAILURE_STATUSES || it.payload?.file == null }
    return PendingUploadUiState(
        groupId = groupId.takeIf { group.any { it.row.status != PendingMutationStatus.Done } },
        inFlight = group.any { it.row.status == PendingMutationStatus.InFlight },
        failedCount = failures.size,
        retryable = group.any { it.canRetry },
        message = if (pending.isEmpty()) null else uploadGroupMessage(pending, failures),
        originals = group.mapIndexed { index, intent ->
            PendingUploadOriginalUi(index + 1, intent.payload?.file?.metadata?.fileName, intent.row.status, intent.receipt?.id)
        },
    )
}

private fun uploadGroupMessage(group: List<PendingUploadIntent>, failures: List<PendingUploadIntent>): UiText {
    val codes = failures.mapNotNull { it.row.lastError?.substringBefore(':') }.toSet()
    return when {
        UPLOAD_CAPACITY_FULL in codes ->
            UiText.res(R.string.pending_msg_upload_capacity_full)
        group.any { it.payload == null } -> UiText.res(R.string.pending_msg_upload_unsupported)
        "outbox_row_expired" in codes ->
            UiText.res(R.string.sync_status_error_expired)
        "upload_original_unavailable" in codes ->
            UiText.res(R.string.pending_msg_upload_unreadable)
        "idempotency_key_reused" in codes ->
            UiText.res(R.string.pending_msg_upload_key_refused)
        codes.any { it in NON_RETRYABLE_UPLOAD_ERRORS } ->
            UiText.res(R.string.pending_msg_upload_original_refused)
        codes.any { it in PROTOCOL_REFUSALS } ->
            UiText.res(R.string.sync_status_error_protocol_mismatch)
        group.any { it.payload?.file == null } ->
            UiText.res(R.string.pending_msg_upload_unreadable)
        failures.isNotEmpty() -> UiText.res(R.string.pending_msg_share_partial_failure, failures.size)
        else -> UiText.res(R.string.pending_msg_upload_saved)
    }
}

private val UPLOAD_FAILURE_STATUSES = setOf(
    PendingMutationStatus.Failed, PendingMutationStatus.Conflict, PendingMutationStatus.Unknown,
)
private val PROTOCOL_REFUSALS = setOf("runtime_version_mismatch", "client_upgrade_required")
