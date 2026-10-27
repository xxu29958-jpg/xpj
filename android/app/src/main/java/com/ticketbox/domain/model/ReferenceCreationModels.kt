package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ReferenceCreated(
    val kind: String,
    @param:Json(name = "public_id") val publicId: String,
    val name: String,
    @param:Json(name = "row_version") val rowVersion: Long,
)
