package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class OriginalCleanupObservation(
    val requestId: String,
    val reason: String,
    val requestedAt: String,
    val policyEnabled: Boolean,
    val image: String? = null,
    val thumbnail: String? = null,
    val imageError: String? = null,
    val thumbnailError: String? = null,
)

data class OriginalHealth(
    val expenseId: Long,
    val publicId: String,
    val rowVersion: Long,
    val state: String,
    val checkedAt: String,
    val expectedSha256: String? = null,
    val observedSha256: String? = null,
    val sizeBytes: Long? = null,
    val mediaType: String? = null,
    val cleanup: OriginalCleanupObservation? = null,
    val cleanupError: String? = null,
)
