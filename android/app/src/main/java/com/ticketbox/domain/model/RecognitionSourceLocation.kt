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
