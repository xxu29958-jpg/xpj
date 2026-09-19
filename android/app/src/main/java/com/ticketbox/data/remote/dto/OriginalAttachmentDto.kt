package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/** Current observation of the original; a cached thumbnail is separate evidence. */
@JsonClass(generateAdapter = true)
data class OriginalHealthDto(
    @param:Json(name = "expense_id") val expenseId: Long,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val state: String,
    @param:Json(name = "checked_at") val checkedAt: String,
    @param:Json(name = "expected_sha256") val expectedSha256: String? = null,
    @param:Json(name = "observed_sha256") val observedSha256: String? = null,
    @param:Json(name = "size_bytes") val sizeBytes: Long? = null,
    @param:Json(name = "media_type") val mediaType: String? = null,
    val cleanup: OriginalCleanupObservationDto? = null,
    @param:Json(name = "cleanup_error") val cleanupError: String? = null,
)

@JsonClass(generateAdapter = true)
data class OriginalCleanupObservationDto(
    @param:Json(name = "request_id") val requestId: String,
    val reason: String,
    @param:Json(name = "requested_at") val requestedAt: String,
    @param:Json(name = "policy_enabled") val policyEnabled: Boolean,
    val image: String? = null,
    val thumbnail: String? = null,
    @param:Json(name = "image_error") val imageError: String? = null,
    @param:Json(name = "thumbnail_error") val thumbnailError: String? = null,
)

/** The stored accepted result. Read health again to learn the current file state. */
@JsonClass(generateAdapter = true)
data class OriginalCommandReceiptDto(
    val operation: String,
    @param:Json(name = "expense_id") val expenseId: Long,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "accepted_at") val acceptedAt: String,
    val sha256: String? = null,
    @param:Json(name = "cleanup_request_id") val cleanupRequestId: String? = null,
    @param:Json(name = "cleanup_pending") val cleanupPending: Boolean? = null,
)

@JsonClass(generateAdapter = true)
data class OriginalVerificationRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "reviewed_sha256") val reviewedSha256: String,
)

@JsonClass(generateAdapter = true)
data class OriginalCleanupRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "request_id") val requestId: String,
)
