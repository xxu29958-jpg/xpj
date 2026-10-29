package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RecognitionFieldChoice(
    val field: String,
    @param:Json(name = "candidate_id") val candidateId: String,
    @param:Json(name = "evidence_public_id") val evidencePublicId: String,
    @param:Json(name = "parser_version") val parserVersion: String,
    val source: String = "image",
    val intent: String = "candidate",
)

@JsonClass(generateAdapter = true)
data class RecognitionFieldCandidate(
    val field: String,
    val id: String,
    // Moshi's string reader preserves a numeric token without passing through Double.
    val value: String,
    val label: String,
    @param:Json(name = "original_text") val originalText: String,
    val explanation: String,
    val role: String,
    @param:Json(name = "can_apply") val canApply: Boolean,
    @param:Json(name = "evidence_public_id") val evidencePublicId: String,
    @param:Json(name = "parser_version") val parserVersion: String,
    @param:Json(name = "currency_code") val currencyCode: String? = null,
    @param:Json(name = "minor_unit_exponent") val minorUnitExponent: Int? = null,
    @param:Json(name = "event_id") val eventId: String? = null,
    val source: String = "image",
    @param:Json(name = "selection_intent") val selectionIntent: String = "candidate",
    @param:Json(name = "event_selected") val eventSelected: Boolean = false,
    @param:Json(name = "source_location") val sourceLocation: RecognitionSourceLocation? = null,
) {
    fun choice() = RecognitionFieldChoice(field, id, evidencePublicId, parserVersion, source, selectionIntent)
}
