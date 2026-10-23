package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RecognitionTimeChoice(
    @param:Json(name = "evidence_public_id") val evidencePublicId: String,
    @param:Json(name = "candidate_id") val candidateId: String,
    @param:Json(name = "parser_version") val parserVersion: String,
    val source: String,
    val intent: String = "candidate",
)

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
    val components: Map<String, Int> = emptyMap(),
    val requiresYear: Boolean = false,
)
