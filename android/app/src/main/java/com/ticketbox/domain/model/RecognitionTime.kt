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
@JsonClass(generateAdapter = true)
data class RecognitionTime(
    @param:Json(name = "evidence_public_id") val evidencePublicId: String,
    @param:Json(name = "parser_version") val parserVersion: String,
    val status: String,
    val candidates: List<RecognitionTimeCandidate>,
    val source: String = "image",
)

@JsonClass(generateAdapter = true)
data class RecognitionTimeCandidate(
    val id: String,
    val label: String,
    val explanation: String,
    @param:Json(name = "original_text") val originalText: String,
    @param:Json(name = "local_value") val localValue: String,
    val precision: String,
    @param:Json(name = "source_timezone") val sourceTimezone: String?,
    @param:Json(name = "source_utc_offset_seconds") val sourceUtcOffsetSeconds: Int?,
    @param:Json(name = "can_apply") val canApply: Boolean,
    @param:Json(name = "evidence_public_id") val evidencePublicId: String? = null,
    val source: String? = null,
    @param:Json(name = "parser_version") val parserVersion: String? = null,
    val role: String = "unknown",
    val components: Map<String, Int> = emptyMap(),
    @param:Json(name = "requires_year") val requiresYear: Boolean = false,
    @param:Json(name = "event_id") val eventId: String? = null,
    @param:Json(name = "event_selected") val eventSelected: Boolean = false,
)
