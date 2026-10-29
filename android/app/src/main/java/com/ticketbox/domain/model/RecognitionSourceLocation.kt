package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RecognitionSourceLocation(
    @param:Json(name = "image_sha256") val imageSha256: String,
    val width: Int,
    val height: Int,
    @param:Json(name = "coordinate_space") val coordinateSpace: String,
    val boxes: List<List<List<Float>>>,
)

@JsonClass(generateAdapter = true)
data class RecognitionTextLine(val text: String, val box: List<Int>)

@JsonClass(generateAdapter = true)
data class RecognitionTextLines(
    @param:Json(name = "evidence_public_id") val evidencePublicId: String,
    @param:Json(name = "image_sha256") val imageSha256: String,
    val width: Int,
    val height: Int,
    @param:Json(name = "coordinate_space") val coordinateSpace: String,
    val lines: List<RecognitionTextLine>,
)
