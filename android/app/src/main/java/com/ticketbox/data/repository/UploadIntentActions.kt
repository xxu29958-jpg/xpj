package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.flow.Flow

/** One original selection. Its UUID must survive an uncertain local acceptance result. */
data class UploadBatchRequest(
    val id: String,
    val imageRefs: List<String>,
    val expectedBinding: LogicalSessionBinding,
    val prepare: suspend (String) -> PreparedUploadImage?,
)

/** Local Room acceptance only; a server receipt is observed on the original row after delivery. */
data class UploadAcceptance(val groupId: String, val rowIds: List<Long>)

data class UploadIntentObservation(val access: LedgerAccessContext?, val uploads: List<PendingUploadIntent>)

data class PendingUploadIntent(
    val row: OutboxRow,
    val payload: UploadScreenshotPayload?,
    val receipt: UploadResponseDto?,
) {
    val canRetry: Boolean
        get() = row.status == PendingMutationStatus.Failed && payload?.file != null &&
            row.lastError?.startsWith("outbox_row_expired") != true &&
            row.lastError?.startsWith("upload_original_unavailable") != true
}

interface UploadIntentActions {
    fun currentUploadBinding(): LogicalSessionBinding?
    fun observeUploadIntents(): Flow<UploadIntentObservation>
    suspend fun acceptUploadBatch(request: UploadBatchRequest): Result<UploadAcceptance>
    suspend fun recoverUploadGroup(expectedBinding: LogicalSessionBinding, groupId: String, drop: Boolean): Result<Unit>
}
