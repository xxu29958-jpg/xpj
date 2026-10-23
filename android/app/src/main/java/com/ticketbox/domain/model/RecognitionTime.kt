package com.ticketbox.domain.model

/** Read-only source evidence. Only a deliberate choice changes the existing edit draft. */
data class RecognitionTime(
    val evidencePublicId: String,
    val parserVersion: String,
    val status: String,
    val candidates: List<RecognitionTimeCandidate>,
    val source: String = "image",
)

data class RecognitionTimeCandidate(
    val id: String,
    val label: String,
    val explanation: String,
    val originalText: String,
    val localValue: String,
    val precision: String,
    val sourceTimezone: String?,
    val sourceUtcOffsetSeconds: Int?,
    val canApply: Boolean,
    val evidencePublicId: String? = null,
    val source: String? = null,
    val parserVersion: String? = null,
    val role: String = "unknown",
)
