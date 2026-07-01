package com.ticketbox.domain.model

data class RecycleBinItem(
    val kind: String,
    val kindLabel: String,
    val resourceId: String,
    val title: String,
    val detail: String,
    val removedAt: String?,
    val retentionLabel: String,
    val expectedRowVersion: Int?,
)

data class RecycleBinSnapshot(
    val items: List<RecycleBinItem>,
    val shortWindowCount: Int,
)
