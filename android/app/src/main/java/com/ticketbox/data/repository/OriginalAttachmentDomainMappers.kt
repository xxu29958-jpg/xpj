package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.OriginalCleanupObservationDto
import com.ticketbox.data.remote.dto.OriginalHealthDto
import com.ticketbox.domain.model.OriginalCleanupObservation
import com.ticketbox.domain.model.OriginalHealth

internal fun OriginalCleanupObservationDto.toDomain(): OriginalCleanupObservation = OriginalCleanupObservation(
    requestId = requestId,
    reason = reason,
    requestedAt = requestedAt,
    policyEnabled = policyEnabled,
    image = image,
    thumbnail = thumbnail,
    imageError = imageError,
    thumbnailError = thumbnailError,
)

internal fun OriginalHealthDto.toDomain(): OriginalHealth = OriginalHealth(
    expenseId = expenseId,
    publicId = publicId,
    rowVersion = rowVersion,
    state = state,
    checkedAt = checkedAt,
    expectedSha256 = expectedSha256,
    observedSha256 = observedSha256,
    sizeBytes = sizeBytes,
    mediaType = mediaType,
    cleanup = cleanup?.toDomain(),
    cleanupError = cleanupError,
)
