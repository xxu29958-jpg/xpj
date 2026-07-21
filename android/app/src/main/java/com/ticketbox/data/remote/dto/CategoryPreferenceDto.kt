package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class CategoryPreferenceDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val name: String,
    val kind: String,
    @param:Json(name = "usage_count")
    val usageCount: Int,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "deleted_at")
    val deletedAt: String?,
)

data class CategoryPreferenceListResponseDto(
    val items: List<CategoryPreferenceDto>,
)

data class CategoryPreferenceTokenRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)
