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
) {
    val isShortWindow: Boolean
        get() = retentionLabel == "短窗可恢复"
}
