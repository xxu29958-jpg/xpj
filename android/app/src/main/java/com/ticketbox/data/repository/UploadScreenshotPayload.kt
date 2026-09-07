package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationType
import java.io.IOException
import java.util.UUID

/** One original share/selection and its position in the persisted continuation group. */
@JsonClass(generateAdapter = true)
data class UploadBatchPosition(val id: String, val index: Int, val count: Int, val groupId: String)

/** Immutable command. A null file records an unreadable slot; it never permits an HTTP send. */
@JsonClass(generateAdapter = true)
data class UploadScreenshotPayload(
    val revision: Int,
    val batch: UploadBatchPosition,
    val origin: LogicalSessionBinding,
    val timezone: String,
    val file: UploadIntentFileDescriptor?,
)

internal const val UPLOAD_UNREADABLE = "upload_source_unreadable"
internal const val UPLOAD_UNSUPPORTED = "upload_intent_unsupported"
internal const val UPLOAD_CAPACITY_FULL = "enrichment_capacity_full"

/** Stable within an original accepted request; another user request has a different batch UUID. */
internal fun uploadItemKey(batchId: String, index: Int): String =
    UUID.nameUUIDFromBytes("$batchId:$index".toByteArray(Charsets.UTF_8)).toString()

internal fun JsonAdapter<UploadScreenshotPayload>.readSupportedUpload(row: OutboxRow): UploadScreenshotPayload? {
    val payload = try {
        fromJson(row.payloadJson)
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    } catch (_: IllegalArgumentException) {
        null
    }
    return payload?.takeIf { it.isSupportedOriginal(row) }
}

private fun UploadScreenshotPayload.isSupportedOriginal(row: OutboxRow): Boolean {
    if (revision != 1 || row.type != PendingMutationType.UploadScreenshot || row.expectedRowVersion != 0L) return false
    if (!batch.isSupported() || row.targetId != "upload_batch:${batch.groupId}" || timezone.isBlank()) return false
    val key = uploadItemKey(batch.id, batch.index)
    if (row.idempotencyKey != key || (file != null && file.key != key)) return false
    return origin.matchesUploadOwner(row)
}

private fun UploadBatchPosition.isSupported(): Boolean =
    isUploadIntentFileKey(id) && isUploadIntentFileKey(groupId) && count in 1..100 && index in 0 until count

private fun LogicalSessionBinding.matchesUploadOwner(row: OutboxRow): Boolean =
    ownerKey.isNotBlank() && ownerKey == row.ownerKey && ledgerId.isNotBlank() && ledgerId == row.ledgerId &&
        canonicalServerOriginOrNull(serverUrl) != null && sessionGeneration.isNotBlank() && bindingRevision.isNotBlank()
