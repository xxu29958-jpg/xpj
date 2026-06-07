package com.ticketbox.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R

@Composable
fun DuplicateNotice(
    reason: String?,
    modifier: Modifier = Modifier,
) {
    AppContentCard(modifier = modifier.fillMaxWidth()) {
        Text(
            text = stringResource(R.string.components_duplicate_notice_title),
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

@Composable
private fun duplicateNoticeMessage(reason: String?): String {
    val normalized = reason.orEmpty().trim()
    return when {
        normalized.contains("图片 hash", ignoreCase = true) ||
            normalized.contains("image hash", ignoreCase = true) ->
            stringResource(R.string.components_duplicate_notice_image_hash)
        normalized.contains("金额") ||
            normalized.contains("商家") ||
            normalized.contains("时间") ->
            stringResource(R.string.components_duplicate_notice_field_match)
        normalized.isNotBlank() -> normalized
        else -> stringResource(R.string.components_duplicate_notice_generic)
    }
}
