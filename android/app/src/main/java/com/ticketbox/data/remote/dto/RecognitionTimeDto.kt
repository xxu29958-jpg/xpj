package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.domain.model.RecognitionTime
import com.ticketbox.domain.model.RecognitionTimeCandidate

@JsonClass(generateAdapter = true)
data class RecognitionTimeDto(
    @param:Json(name = "evidence_public_id") val evidencePublicId: String,
    @param:Json(name = "parser_version") val parserVersion: String,
    val status: String,
    val candidates: List<RecognitionTimeCandidateDto>,
    val source: String = "image",
) {
    fun toDomain() = RecognitionTime(evidencePublicId, parserVersion, status, candidates.map { it.toDomain() }, source)
}

@JsonClass(generateAdapter = true)
data class RecognitionTimeCandidateDto(
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
) {
    fun toDomain() = RecognitionTimeCandidate(id, label, explanation, originalText, localValue,
        precision, sourceTimezone, sourceUtcOffsetSeconds, canApply, evidencePublicId, source, parserVersion, role)
}
