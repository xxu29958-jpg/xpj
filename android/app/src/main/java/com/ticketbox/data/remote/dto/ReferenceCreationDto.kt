package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

data class ReferenceCreateRequestDto(val name: String)

@JsonClass(generateAdapter = true)
data class ReferenceCreatedDto(
    val kind: String,
    @param:Json(name = "public_id") val publicId: String,
    val name: String,
    @param:Json(name = "row_version") val rowVersion: Long,
)
