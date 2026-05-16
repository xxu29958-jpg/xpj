package com.ticketbox.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun DuplicateNotice(
    reason: String?,
    modifier: Modifier = Modifier,
) {
    AppContentCard(modifier = modifier.fillMaxWidth()) {
        Text(
            text = "可能重复上传",
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.labelLarge,
        )
        Text(
            text = duplicateNoticeMessage(reason),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

private fun duplicateNoticeMessage(reason: String?): String {
    val normalized = reason.orEmpty().trim()
    return when {
        normalized.contains("图片 hash", ignoreCase = true) ||
            normalized.contains("image hash", ignoreCase = true) ->
            "这张截图和之前上传过的一张完全一致。确认前先看一眼，确实要记账就点“不是重复，保留”。"
        normalized.contains("金额") ||
            normalized.contains("商家") ||
            normalized.contains("时间") ->
            "这笔账单和已有记录很接近。确认前先看一眼，避免重复入账。"
        normalized.isNotBlank() -> normalized
        else -> "这笔账单可能已经上传过。确认前先看一眼，避免重复入账。"
    }
}
