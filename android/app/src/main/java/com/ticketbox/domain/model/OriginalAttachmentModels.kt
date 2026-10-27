package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class OriginalCleanupObservation(
    @param:Json(name = "request_id") val requestId: String,
    val reason: String,
    @param:Json(name = "requested_at") val requestedAt: String,
    @param:Json(name = "policy_enabled") val policyEnabled: Boolean,
    val image: String? = null,
    val thumbnail: String? = null,
    @param:Json(name = "image_error") val imageError: String? = null,
    @param:Json(name = "thumbnail_error") val thumbnailError: String? = null,
)

@JsonClass(generateAdapter = true)
data class OriginalHealth(
    @param:Json(name = "expense_id") val expenseId: Long,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val state: String,
    @param:Json(name = "checked_at") val checkedAt: String,
    @param:Json(name = "expected_sha256") val expectedSha256: String? = null,
    @param:Json(name = "observed_sha256") val observedSha256: String? = null,
    @param:Json(name = "size_bytes") val sizeBytes: Long? = null,
    @param:Json(name = "media_type") val mediaType: String? = null,
    val cleanup: OriginalCleanupObservation? = null,
    @param:Json(name = "cleanup_error") val cleanupError: String? = null,
)
