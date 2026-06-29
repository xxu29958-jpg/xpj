package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class RecycleBinItemDto(
    val kind: String,
    @param:Json(name = "kind_label")
    val kindLabel: String,
    @param:Json(name = "resource_id")
    val resourceId: String,
    val title: String,
    val detail: String,
    @param:Json(name = "removed_at")
    val removedAt: String? = null,
    @param:Json(name = "retention_label")
    val retentionLabel: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Int? = null,
)

data class RecycleBinListResponseDto(
    val items: List<RecycleBinItemDto>,
    @param:Json(name = "short_window_count")
    val shortWindowCount: Int,
)

data class RecycleBinRestoreRequestDto(
    val kind: String,
    @param:Json(name = "resource_id")
    val resourceId: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Int? = null,
)

data class RecycleBinRestoreResponseDto(
    val message: String,
)
