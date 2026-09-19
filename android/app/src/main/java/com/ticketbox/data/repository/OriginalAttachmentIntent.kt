package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.OriginalCommandReceiptDto
import com.ticketbox.data.remote.dto.OriginalHealthDto
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.flow.Flow

/** Same-bill command evidence. Neither a health cache nor a new upload receipt. */
@JsonClass(generateAdapter = true)
data class OriginalAttachmentPayload(
    val revision: Int = 1,
    val operation: String,
    val expenseId: Long,
    val publicId: String,
    val expectedRowVersion: Long,
    val origin: LogicalSessionBinding,
    val sha256: String? = null,
    val cleanupRequestId: String? = null,
    val file: UploadIntentFileDescriptor? = null,
)

data class OriginalSubmission(val key: String, val payload: OriginalAttachmentPayload,
    val prepare: (suspend () -> PreparedUploadImage?)? = null)

data class PendingOriginalCommand(val row: OutboxRow, val payload: OriginalAttachmentPayload?,
    val receipt: OriginalCommandReceiptDto?) {
    val delivered: Boolean get() = row.status == PendingMutationStatus.Done && receipt != null
    val canRetry: Boolean get() = payload != null && row.status == PendingMutationStatus.Failed &&
        row.lastError?.substringBefore(':') !in ORIGINAL_REVIEW_ERRORS &&
        row.lastError?.startsWith("outbox_row_expired") != true
    val canDiscard: Boolean get() = row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
}

data class OriginalCommandObservation(val access: LedgerAccessContext?, val commands: List<PendingOriginalCommand>)

interface OriginalAttachmentActions {
    fun currentOriginalBinding(): LogicalSessionBinding?
    fun observeOriginalCommands(): Flow<OriginalCommandObservation>
    suspend fun fetchOriginalHealth(id: Long): Result<OriginalHealthDto>
    suspend fun submitOriginal(request: OriginalSubmission): Result<Long>
    suspend fun recoverOriginal(binding: LogicalSessionBinding, rowId: Long, drop: Boolean): Result<Unit>
}

internal val ORIGINAL_REVIEW_ERRORS = setOf("image_replenishment_mismatch", "original_identity_unverified",
    "original_review_conflict", "original_already_verified", "attachment_cleanup_changed", "attachment_cleanup_invalid",
    "state_conflict", "idempotency_key_reused", "original_intent_unsupported",
    "original_receipt_invalid", "upload_original_unavailable", "expense_not_found", "image_not_found")
internal val originalPayloadAdapter = Moshi.Builder().build().adapter(OriginalAttachmentPayload::class.java)
internal val originalReceiptAdapter = Moshi.Builder().build().adapter(OriginalCommandReceiptDto::class.java)
internal val originalHealthAdapter = Moshi.Builder().build().adapter(OriginalHealthDto::class.java)

internal fun readOriginalPayload(row: OutboxRow): OriginalAttachmentPayload? =
    runCatching { originalPayloadAdapter.fromJson(row.payloadJson) }.getOrNull()?.takeIf {
        row.type == PendingMutationType.OriginalAttachment && it.supported() &&
            row.targetId == "expense:${it.expenseId}" && row.expectedRowVersion == it.expectedRowVersion &&
            isUploadIntentFileKey(row.idempotencyKey.orEmpty()) && (it.file == null || it.file.key == row.idempotencyKey) &&
            it.origin.ownerKey == row.ownerKey && it.origin.ledgerId == row.ledgerId
    }

internal fun OriginalAttachmentPayload.supported(): Boolean = revision == 1 && expenseId > 0 && publicId.isNotBlank() &&
    expectedRowVersion > 0 && origin.ownerKey.isNotBlank() && origin.ledgerId.isNotBlank() &&
    origin.sessionGeneration.isNotBlank() && origin.bindingRevision.isNotBlank() && operationSupported()

private fun OriginalAttachmentPayload.operationSupported(): Boolean = when (operation) {
        "verify_original" -> sha256.isOriginalDigest() && file == null && cleanupRequestId == null
        "replenish_original" -> sha256.isOriginalDigest() && file != null && cleanupRequestId == null
        "retry_original_cleanup", "cancel_original_cleanup" ->
            isUploadIntentFileKey(cleanupRequestId.orEmpty()) && sha256 == null && file == null
        else -> false
    }

internal fun String?.isOriginalDigest(): Boolean = this?.matches(Regex("[0-9a-f]{64}")) == true
