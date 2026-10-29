package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class OriginalTextFeedback(
    val field: String,
    @param:Json(name = "image_sha256") val imageSha256: String,
    val width: Int,
    val height: Int,
    @param:Json(name = "coordinate_space") val coordinateSpace: String = "exif-transposed-pixels",
    @param:Json(name = "location_state") val locationState: String = "unlocated",
    val point: List<Float>? = null,
    val box: List<Float>? = null,
    @param:Json(name = "verbatim_text") val verbatimText: String = "",
    val role: String,
    val issue: String = "transcription",
    @param:Json(name = "text_verified") val textVerified: Boolean = false,
    @param:Json(name = "evidence_public_id") val evidencePublicId: String? = null,
)
