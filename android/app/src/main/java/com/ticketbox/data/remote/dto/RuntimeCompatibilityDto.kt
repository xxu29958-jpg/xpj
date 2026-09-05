package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class RuntimeCompatibilityDto(
    @param:Json(name = "write_compatibility")
    val writeCompatibility: String,
)
